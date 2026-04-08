"""PyBaMM driver for sim.

PyBaMM is a pure-Python battery simulation library. The "solver" IS the
pybamm pip package — there is no separate binary, no JVM, no native
process to launch. Detection therefore boils down to "which Python envs
on this host can `import pybamm`?" — and the only ones we know about
are (a) sim's core Python and (b) any bootstrapped profile env under
``$SIM_DIR/envs/pybamm_*``.

Crucially, this driver MUST NOT import pybamm from the core process —
pybamm pulls in casadi, scipy, jax (optional), and a 200 MB dep tree.
We probe for it via subprocess instead, so `sim check pybamm` stays
sub-second when pybamm isn't installed.
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from sim.driver import ConnectionInfo, Diagnostic, LintResult, SolverInstall
from sim.runner import run_subprocess


def _probe_python_for_pybamm(python_exe: Path) -> str | None:
    """Run `<python> -c 'import pybamm; print(pybamm.__version__)'` and
    return the version string, or None if pybamm is not importable there.

    Pure subprocess — never imports pybamm into the calling process.
    Times out at 5s so a hung interpreter doesn't block detection.
    """
    if not python_exe.is_file():
        return None
    try:
        result = subprocess.run(
            [str(python_exe), "-c", "import pybamm; print(pybamm.__version__)"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


class PyBaMMLDriver:
    @property
    def name(self) -> str:
        return "pybamm"

    def detect(self, script: Path) -> bool:
        """Check if script imports pybamm."""
        text = script.read_text()
        return bool(re.search(r"^\s*(import pybamm|from pybamm\b)", text, re.MULTILINE))

    def lint(self, script: Path) -> LintResult:
        """Validate a PyBaMM script."""
        text = script.read_text()
        diagnostics: list[Diagnostic] = []

        # Check: pybamm imported?
        has_import = bool(
            re.search(r"^\s*(import pybamm|from pybamm\b)", text, re.MULTILINE)
        )
        if not has_import:
            # Check if pybamm is used without import
            if "pybamm" in text:
                diagnostics.append(
                    Diagnostic(
                        level="error",
                        message="Script uses pybamm but does not import it",
                    )
                )
            else:
                diagnostics.append(
                    Diagnostic(level="error", message="No pybamm import found")
                )

        # Check: syntax valid?
        try:
            ast.parse(text)
        except SyntaxError as e:
            diagnostics.append(
                Diagnostic(level="error", message=f"Syntax error: {e}", line=e.lineno)
            )

        # Check: .solve() called? (AST-based, ignores comments)
        if has_import:
            try:
                tree = ast.parse(text)
                has_solve = any(
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "solve"
                    for node in ast.walk(tree)
                )
                if not has_solve:
                    diagnostics.append(
                        Diagnostic(
                            level="warning",
                            message="No .solve() call found — script may not run a simulation",
                        )
                    )
            except SyntaxError:
                pass  # Already caught above

        ok = not any(d.level == "error" for d in diagnostics)
        return LintResult(ok=ok, diagnostics=diagnostics)

    def connect(self) -> ConnectionInfo:
        """Lightweight availability check via detect_installed.

        Reports the highest version found across all probed Python envs.
        Does not import pybamm (which would pull in casadi/scipy/...).
        """
        installs = self.detect_installed()
        if not installs:
            return ConnectionInfo(
                solver="pybamm",
                version=None,
                status="not_installed",
                message="pybamm is not importable from any known Python env",
            )
        top = installs[0]
        return ConnectionInfo(
            solver="pybamm",
            version=top.version,
            status="ok",
            message=f"pybamm {top.version} importable in {top.path}",
            solver_version=top.version,
        )

    def detect_installed(self) -> list[SolverInstall]:
        """Find every Python env on this host that can `import pybamm`.

        Strategy:
          1. The current Python (sim core) — quick subprocess probe
          2. Each .sim/envs/pybamm_*/python subprocess
          3. ``which python`` and ``which python3`` if different

        Pure subprocess. Does NOT import pybamm into core sim. Times out
        per env at 5s. Returns highest version first.
        """
        found: dict[str, SolverInstall] = {}

        def _record(python: Path, source: str) -> None:
            ver = _probe_python_for_pybamm(python)
            if ver is None:
                return
            key = str(python.resolve())
            if key in found:
                return
            short = ".".join(ver.split(".")[:2])
            found[key] = SolverInstall(
                name="pybamm",
                version=short,
                path=str(python.parent),
                source=source,
                extra={"raw_version": ver, "python": str(python)},
            )

        # 1) sim core's Python
        _record(Path(sys.executable), source="env:sys.executable")

        # 2) Bootstrapped pybamm_* profile envs
        sim_dir = Path(os.environ.get("SIM_DIR") or (Path.cwd() / ".sim"))
        envs_root = sim_dir / "envs"
        if envs_root.is_dir():
            for child in sorted(envs_root.iterdir()):
                if not child.name.startswith("pybamm_"):
                    continue
                py = child / ("Scripts" if os.name == "nt" else "bin") / (
                    "python.exe" if os.name == "nt" else "python"
                )
                _record(py, source=f"profile-env:{child.name}")

        # 3) PATH probe (separate from sys.executable when sim is run via uv etc.)
        import shutil
        for name in ("python3", "python"):
            p = shutil.which(name)
            if p:
                _record(Path(p), source=f"which:{name}")

        return sorted(found.values(), key=lambda i: i.version, reverse=True)

    def parse_output(self, stdout: str) -> dict:
        """Parse structured JSON output from a PyBaMM script."""
        # Convention: script prints a JSON object (possibly among other output).
        # We take the last line that parses as JSON.
        for line in reversed(stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        return {}

    def run_file(self, script: Path):
        """Execute a PyBaMM Python script."""
        return run_subprocess(
            [sys.executable, str(script)],
            script=script,
            solver=self.name,
        )
