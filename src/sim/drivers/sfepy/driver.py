"""SfePy driver for sim.

SfePy (Simple Finite Elements in Python) is a pure-Python FEM framework
for solving PDEs by the finite element method. Pip-installable wheel
(`pip install sfepy`), no C++ dependency for the user (compiled bits
ride along inside the wheel).

Two usage modes:
    1. Declarative `problem description` files run via `sfepy-run`
    2. Direct API: `from sfepy.discrete import Problem, ...`

The driver supports mode 2 (consistent with other Python solvers).
"""
from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from sim.driver import ConnectionInfo, Diagnostic, LintResult, SolverInstall
from sim.runner import run_subprocess


_IMPORT_RE = re.compile(r"^\s*(import\s+sfepy|from\s+sfepy\b)", re.MULTILINE)
_USAGE_RE = re.compile(
    r"\b(Problem|FieldVariable|Equation|Equations|Material|Term\.new|"
    r"Field\.from_args|FEDomain|Mesh|EssentialBC|gen_block_mesh)\b",
)


def _probe_python_for_sfepy(python_exe: Path) -> str | None:
    if not python_exe.is_file():
        return None
    try:
        proc = subprocess.run(
            [str(python_exe), "-c", "import sfepy; print(sfepy.__version__)"],
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    v = (proc.stdout or "").strip()
    return v or None


class SfepyDriver:
    """Sim driver for SfePy (pure-Python FEM)."""

    @property
    def name(self) -> str:
        return "sfepy"

    @property
    def supports_session(self) -> bool:
        return False

    def detect(self, script: Path) -> bool:
        try:
            if script.suffix.lower() != ".py":
                return False
            text = script.read_text(encoding="utf-8", errors="replace")
            return bool(_IMPORT_RE.search(text))
        except (OSError, UnicodeDecodeError):
            return False

    def lint(self, script: Path) -> LintResult:
        diagnostics: list[Diagnostic] = []
        if script.suffix.lower() != ".py":
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(
                    level="error",
                    message=f"Unsupported file type: {script.suffix} (expected .py)",
                )],
            )
        try:
            text = script.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(level="error", message=f"Cannot read: {e}")],
            )

        if not _IMPORT_RE.search(text):
            diagnostics.append(Diagnostic(
                level="error",
                message="No `import sfepy` / `from sfepy` found",
            ))

        try:
            ast.parse(text)
        except SyntaxError as e:
            diagnostics.append(Diagnostic(
                level="error", message=f"Syntax error: {e}", line=e.lineno,
            ))

        if _IMPORT_RE.search(text) and not _USAGE_RE.search(text):
            diagnostics.append(Diagnostic(
                level="warning",
                message=(
                    "No Problem / FieldVariable / Term.new / Mesh call — "
                    "script may not do anything"
                ),
            ))

        ok = not any(d.level == "error" for d in diagnostics)
        return LintResult(ok=ok, diagnostics=diagnostics)

    def connect(self) -> ConnectionInfo:
        installs = self.detect_installed()
        if not installs:
            return ConnectionInfo(
                solver="sfepy", version=None, status="not_installed",
                message="sfepy not importable from any known Python env",
            )
        top = installs[0]
        return ConnectionInfo(
            solver="sfepy", version=top.version, status="ok",
            message=f"SfePy {top.version} in {top.path}",
            solver_version=top.version,
        )

    def detect_installed(self) -> list[SolverInstall]:
        found: dict[str, SolverInstall] = {}

        def _record(python: Path, source: str) -> None:
            ver = _probe_python_for_sfepy(python)
            if ver is None:
                return
            key = str(python.resolve())
            if key in found:
                return
            short = ".".join(ver.split(".")[:2]) if ver != "unknown" else "unknown"
            found[key] = SolverInstall(
                name="sfepy", version=short,
                path=str(python.parent), source=source,
                extra={"raw_version": ver, "python": str(python)},
            )

        _record(Path(sys.executable), "sys.executable")
        for name in ("python3", "python"):
            p = shutil.which(name)
            if p:
                _record(Path(p), f"which:{name}")
        return sorted(found.values(), key=lambda i: i.version, reverse=True)

    def parse_output(self, stdout: str) -> dict:
        for line in reversed(stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        return {}

    def run_file(self, script: Path):
        if script.suffix.lower() != ".py":
            raise RuntimeError(
                f"sfepy driver only accepts .py scripts (got {script.suffix})"
            )
        installs = self.detect_installed()
        if not installs:
            raise RuntimeError("SfePy is not installed in any known Python env")
        python_exe = installs[0].extra.get("python", sys.executable)
        return run_subprocess(
            [python_exe, str(script)], script=script, solver=self.name,
        )

    # Session lifecycle stubs — one-shot driver, but DriverProtocol is
    # runtime_checkable so every method must exist. See `sim.driver`.
    def launch(self, **kwargs) -> dict:
        raise NotImplementedError(f"{self.name} driver does not support sessions")

    def run(self, code: str, label: str = "") -> dict:
        raise NotImplementedError(f"{self.name} driver does not support sessions")

    def disconnect(self) -> dict:
        return {"ok": True, "disconnected": True}
