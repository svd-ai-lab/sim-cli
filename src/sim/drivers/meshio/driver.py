"""meshio driver for sim.

meshio is a pure-Python mesh format converter (20+ formats: Gmsh, VTK,
XDMF, CGNS, STL, Abaqus .inp, OpenFOAM, ...). Used to bridge between
sim's existing drivers (Gmsh → CalculiX, Gmsh → Elmer, etc.) — a
"glue" for the mesher/solver pipeline.

Usage:
    - Python scripts `import meshio` that call `read` / `write` / `convert`
    - No separate binary; `meshio` CLI is also Python (installed alongside)

Detection mode mirrors PyBaMM / scikit-fem: import probe via subprocess.
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from sim.driver import ConnectionInfo, Diagnostic, LintResult, SolverInstall
from sim.runner import run_subprocess


_IMPORT_RE = re.compile(r"^\s*(import\s+meshio|from\s+meshio\b)", re.MULTILINE)
_IO_RE = re.compile(r"\bmeshio\.(read|write|convert|Mesh)\b")


def _probe_python_for_meshio(python_exe: Path) -> str | None:
    if not python_exe.is_file():
        return None
    try:
        proc = subprocess.run(
            [str(python_exe), "-c", "import meshio; print(meshio.__version__)"],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    return (proc.stdout or "").strip() or None


class MeshioDriver:
    """Sim driver for meshio (pure-Python mesh format converter)."""

    @property
    def name(self) -> str:
        return "meshio"

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
                level="error", message="No `import meshio` / `from meshio` found",
            ))

        try:
            ast.parse(text)
        except SyntaxError as e:
            diagnostics.append(Diagnostic(
                level="error", message=f"Syntax error: {e}", line=e.lineno,
            ))

        if _IMPORT_RE.search(text) and not _IO_RE.search(text):
            diagnostics.append(Diagnostic(
                level="warning",
                message="No meshio.read/write/convert/Mesh call — script may not do anything",
            ))

        ok = not any(d.level == "error" for d in diagnostics)
        return LintResult(ok=ok, diagnostics=diagnostics)

    def connect(self) -> ConnectionInfo:
        installs = self.detect_installed()
        if not installs:
            return ConnectionInfo(
                solver="meshio", version=None, status="not_installed",
                message="meshio is not importable from any known Python env",
            )
        top = installs[0]
        return ConnectionInfo(
            solver="meshio", version=top.version, status="ok",
            message=f"meshio {top.version} importable in {top.path}",
            solver_version=top.version,
        )

    def detect_installed(self) -> list[SolverInstall]:
        found: dict[str, SolverInstall] = {}

        def _record(python: Path, source: str) -> None:
            ver = _probe_python_for_meshio(python)
            if ver is None:
                return
            key = str(python.resolve())
            if key in found:
                return
            short = ".".join(ver.split(".")[:2])
            found[key] = SolverInstall(
                name="meshio", version=short,
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
                f"meshio driver only accepts .py scripts (got {script.suffix})"
            )
        installs = self.detect_installed()
        if not installs:
            raise RuntimeError("meshio is not installed in any known Python env")
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
