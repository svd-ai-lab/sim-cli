"""PyMFEM driver for sim.

MFEM is a high-performance C++ finite-element library from LLNL. PyMFEM
is the Python binding (`pip install mfem`), distributed as a pip wheel
with a bundled C++ MFEM build.

Two Python modules:
    import mfem.ser   # serial
    import mfem.par   # MPI-parallel (requires separate build)

Our driver uses the serial module by default. Agent scripts write
.py that `import mfem.ser as mfem` and construct meshes, finite-element
spaces, bilinear/linear forms, and solve.
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


_IMPORT_RE = re.compile(r"^\s*(import\s+mfem|from\s+mfem\b)", re.MULTILINE)
_USAGE_RE = re.compile(
    r"\bmfem\.(Mesh|FiniteElementSpace|BilinearForm|LinearForm|GridFunction|Vector)|"
    r"\.GetNV\b|\.GetNE\b|\.FormLinearSystem\b",
)


def _probe_python_for_mfem(python_exe: Path) -> str | None:
    if not python_exe.is_file():
        return None
    # Probe 1: version via importlib.metadata (fast, no C extension load)
    try:
        proc = subprocess.run(
            [str(python_exe), "-c",
             "import importlib.metadata as md; print(md.version('mfem'))"],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode == 0:
        v = (proc.stdout or "").strip()
        if v:
            # Verify mfem.ser actually loads (not just metadata)
            try:
                p2 = subprocess.run(
                    [str(python_exe), "-c", "import mfem.ser"],
                    capture_output=True, text=True, timeout=30,
                )
            except (subprocess.TimeoutExpired, OSError):
                return None
            if p2.returncode != 0:
                return None
            return v
    return None


class PymfemDriver:
    """Sim driver for PyMFEM (Python bindings for MFEM C++ FEM library)."""

    @property
    def name(self) -> str:
        return "pymfem"

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
                level="error", message="No `import mfem` / `from mfem` found",
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
                message="No mfem.Mesh / FiniteElementSpace / BilinearForm call — script may not do anything",
            ))

        ok = not any(d.level == "error" for d in diagnostics)
        return LintResult(ok=ok, diagnostics=diagnostics)

    def connect(self) -> ConnectionInfo:
        installs = self.detect_installed()
        if not installs:
            return ConnectionInfo(
                solver="pymfem", version=None, status="not_installed",
                message="mfem not importable from any known Python env",
            )
        top = installs[0]
        return ConnectionInfo(
            solver="pymfem", version=top.version, status="ok",
            message=f"PyMFEM {top.version} in {top.path}",
            solver_version=top.version,
        )

    def detect_installed(self) -> list[SolverInstall]:
        found: dict[str, SolverInstall] = {}

        def _record(python: Path, source: str) -> None:
            ver = _probe_python_for_mfem(python)
            if ver is None:
                return
            key = str(python.resolve())
            if key in found:
                return
            short = ".".join(ver.split(".")[:2]) if ver != "unknown" else "unknown"
            found[key] = SolverInstall(
                name="pymfem", version=short,
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
                f"pymfem driver only accepts .py scripts (got {script.suffix})"
            )
        installs = self.detect_installed()
        if not installs:
            raise RuntimeError("PyMFEM is not installed in any known Python env")
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
