"""Gmsh driver for sim.

Gmsh is an open-source finite-element mesh generator by Geuzaine and
Remacle. It reads two script types:
    .geo  — Gmsh native DSL (geometry + meshing commands)
    .py   — Python scripts using `import gmsh`

Gmsh is a **pre-processor** (mesher), not a solver. Its "result" is a
`.msh` mesh file. Acceptance = topology (node/element counts, bbox).

Installation path we target: `pip install gmsh` which ships a
self-contained wheel including both the Python module and a CLI wrapper.
The CLI wrapper at `<venv>/bin/gmsh` is a short Python script of the form:

    #!/usr/bin/env python
    import sys, gmsh
    gmsh.initialize(sys.argv, run=True)
    gmsh.finalize()

We invoke it explicitly via the venv's python interpreter to avoid PATH
shebang issues.
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from sim.driver import ConnectionInfo, Diagnostic, LintResult, RunResult, SolverInstall


_GMSH_IMPORT_RE = re.compile(r"^\s*(?:import\s+gmsh|from\s+gmsh\b)", re.MULTILINE)
# Core GEO-kernel + OpenCASCADE commands that indicate a real Gmsh script
_GEO_GEOM_RE = re.compile(
    r"\b(Point|Line|Circle|Ellipse|Spline|BSpline|Bezier|"
    r"Surface|Volume|Sphere|Box|Cylinder|Cone|Torus|"
    r"Rectangle|Disk|Curve\s+Loop|Surface\s+Loop|Extrude|Revolve|"
    r"Physical\s+(?:Point|Curve|Line|Surface|Volume)|"
    r"SetFactory)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def _probe_gmsh_version(python_exe: Path) -> str | None:
    """Run python -c 'import gmsh; print version' via subprocess."""
    if not python_exe.is_file():
        return None
    try:
        proc = subprocess.run(
            [str(python_exe), "-c",
             "import gmsh; gmsh.initialize(); "
             "print(gmsh.option.getString('General.Version')); gmsh.finalize()"],
            capture_output=True, text=True, timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    for line in reversed(proc.stdout.strip().splitlines()):
        line = line.strip()
        if re.match(r"^\d+\.\d+", line):
            return line
    return None


def _make_install(python_exe: Path, cli_script: Path | None, source: str) -> SolverInstall | None:
    version = _probe_gmsh_version(python_exe)
    if version is None:
        return None
    extra = {"python": str(python_exe)}
    if cli_script and cli_script.is_file():
        extra["cli"] = str(cli_script)
    short = ".".join(version.split(".")[:2])
    return SolverInstall(
        name="gmsh", version=short,
        path=str(python_exe.parent), source=source,
        extra={**extra, "raw_version": version},
    )


def _candidates_from_env() -> list[tuple[Path, Path | None, str]]:
    out = []
    for var in ("GMSH_HOME", "GMSH_BIN"):
        val = os.environ.get(var)
        if not val:
            continue
        p = Path(val)
        if p.is_file():
            # If GMSH_BIN points to the CLI script, look for python next to it
            py = p.parent / "python"
            if not py.is_file():
                py = p.parent / "python3"
            out.append((py, p, f"env:{var}"))
        elif p.is_dir():
            for name in ("python", "python3"):
                py = p / "bin" / name
                if py.is_file():
                    cli = p / "bin" / "gmsh"
                    out.append((py, cli if cli.is_file() else None, f"env:{var}"))
    return out


def _candidates_from_current_venv() -> list[tuple[Path, Path | None, str]]:
    """If sim is running in a venv that has gmsh installed, use that."""
    here = Path(sys.executable)
    cli = here.parent / "gmsh"
    return [(here, cli if cli.is_file() else None, "sys.executable")]


def _candidates_from_path() -> list[tuple[Path, Path | None, str]]:
    out = []
    gmsh_cli = shutil.which("gmsh")
    if gmsh_cli:
        cli = Path(gmsh_cli).resolve()
        for name in ("python", "python3"):
            py = cli.parent / name
            if py.is_file():
                out.append((py, cli, "which:gmsh"))
                break
        else:
            # Fall back to the current interpreter
            out.append((Path(sys.executable), cli, "which:gmsh"))
    return out


_FINDERS = [
    _candidates_from_env,
    _candidates_from_current_venv,
    _candidates_from_path,
]


def _scan_gmsh_installs() -> list[SolverInstall]:
    found: dict[str, SolverInstall] = {}
    for finder in _FINDERS:
        try:
            candidates = finder()
        except Exception:
            continue
        for python_exe, cli, source in candidates:
            key = str(python_exe.resolve())
            if key in found:
                continue
            inst = _make_install(python_exe, cli, source)
            if inst is not None:
                found[key] = inst
    return sorted(found.values(), key=lambda i: i.version, reverse=True)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


class GmshDriver:
    """Sim driver for Gmsh (finite-element mesh generator)."""

    @property
    def name(self) -> str:
        return "gmsh"

    @property
    def supports_session(self) -> bool:
        return False

    # -- detect ---------------------------------------------------------------

    def detect(self, script: Path) -> bool:
        try:
            suffix = script.suffix.lower()
            if suffix == ".geo":
                script.read_text(encoding="utf-8", errors="replace")
                return True
            if suffix == ".py":
                text = script.read_text(encoding="utf-8", errors="replace")
                return bool(_GMSH_IMPORT_RE.search(text))
        except (OSError, UnicodeDecodeError):
            pass
        return False

    # -- lint -----------------------------------------------------------------

    def lint(self, script: Path) -> LintResult:
        diagnostics: list[Diagnostic] = []
        suffix = script.suffix.lower()

        if suffix not in (".geo", ".py"):
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(
                    level="error",
                    message=f"Unsupported file type: {suffix} (expected .geo or .py)",
                )],
            )

        try:
            text = script.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(level="error", message=f"Cannot read: {e}")],
            )

        if suffix == ".geo":
            return self._lint_geo(text, diagnostics)
        return self._lint_py(text, diagnostics)

    def _lint_geo(self, text: str, diagnostics: list[Diagnostic]) -> LintResult:
        stripped = "\n".join(
            line for line in text.splitlines()
            if not line.strip().startswith("//")
        )
        if not _GEO_GEOM_RE.search(stripped):
            diagnostics.append(Diagnostic(
                level="warning",
                message="No geometry commands found (Point, Sphere, Surface, Extrude, etc.)",
            ))
        # Basic bracket balance check
        if stripped.count("{") != stripped.count("}"):
            diagnostics.append(Diagnostic(
                level="error",
                message="Unbalanced braces — likely a syntax error",
            ))
        ok = not any(d.level == "error" for d in diagnostics)
        return LintResult(ok=ok, diagnostics=diagnostics)

    def _lint_py(self, text: str, diagnostics: list[Diagnostic]) -> LintResult:
        if not _GMSH_IMPORT_RE.search(text):
            diagnostics.append(Diagnostic(
                level="error", message="No 'import gmsh' found",
            ))
        try:
            ast.parse(text)
        except SyntaxError as e:
            diagnostics.append(Diagnostic(
                level="error", message=f"Syntax error: {e}", line=e.lineno,
            ))
        ok = not any(d.level == "error" for d in diagnostics)
        return LintResult(ok=ok, diagnostics=diagnostics)

    # -- connect --------------------------------------------------------------

    def connect(self) -> ConnectionInfo:
        installs = self.detect_installed()
        if not installs:
            return ConnectionInfo(
                solver="gmsh", version=None, status="not_installed",
                message="Gmsh not importable — `pip install gmsh` in sim's env",
            )
        top = installs[0]
        return ConnectionInfo(
            solver="gmsh", version=top.version, status="ok",
            message=f"Gmsh {top.extra.get('raw_version', top.version)} via {top.path}",
            solver_version=top.version,
        )

    def detect_installed(self) -> list[SolverInstall]:
        return _scan_gmsh_installs()

    # -- parse_output ---------------------------------------------------------

    def parse_output(self, stdout: str) -> dict:
        for line in reversed(stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        return {}

    # -- run_file -------------------------------------------------------------

    def run_file(self, script: Path) -> RunResult:
        installs = self.detect_installed()
        if not installs:
            raise RuntimeError("Gmsh is not installed on this host")

        suffix = script.suffix.lower()
        if suffix not in (".geo", ".py"):
            raise RuntimeError(f"Gmsh only accepts .geo or .py (got {suffix})")

        top = installs[0]
        python_exe = top.extra.get("python", sys.executable)
        cli_script = top.extra.get("cli")
        work_dir = script.parent

        if suffix == ".geo":
            if not cli_script:
                raise RuntimeError("Gmsh CLI wrapper not found — cannot run .geo")
            out_msh = script.with_suffix(".msh").name
            cmd = [python_exe, cli_script, script.name,
                   "-3", "-o", out_msh, "-format", "msh22"]
        else:  # .py
            cmd = [python_exe, str(script)]

        start = time.monotonic()
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                cwd=str(work_dir), timeout=300,
            )
        except subprocess.TimeoutExpired:
            return RunResult(
                exit_code=-1, stdout="", stderr="Gmsh timed out after 300s",
                duration_s=round(time.monotonic() - start, 3),
                script=str(script), solver=self.name,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        duration = time.monotonic() - start

        return RunResult(
            exit_code=proc.returncode,
            stdout=proc.stdout.strip() if proc.stdout else "",
            stderr=proc.stderr.strip() if proc.stderr else "",
            duration_s=round(duration, 3),
            script=str(script), solver=self.name,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    # Session lifecycle stubs — one-shot driver, but DriverProtocol is
    # runtime_checkable so every method must exist. See `sim.driver`.
    def launch(self, **kwargs) -> dict:
        raise NotImplementedError(f"{self.name} driver does not support sessions")

    def run(self, code: str, label: str = "") -> dict:
        raise NotImplementedError(f"{self.name} driver does not support sessions")

    def disconnect(self) -> dict:
        return {"ok": True, "disconnected": True}
