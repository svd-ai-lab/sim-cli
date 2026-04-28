"""ParaView driver for sim.

ParaView is an open-source data visualization and analysis application
built on VTK, developed by Kitware / Sandia / LANL / LLNL. Used as
sim's heavyweight post-processor for large-scale CFD/FEA result
visualization, parallel rendering, and batch image generation.

Two execution models:
  Phase 1 (one-shot): pvpython / pvbatch script.py
  Phase 2 (session):  pvserver + paraview.simple.Connect() for interactive
                      pipeline construction

Typical agent workflow:
    1. Solver writes .vtu / .vtk / .case / .foam / .cgns
    2. ParaView reads the file, applies filters, renders images
    3. Emit JSON of acceptance metrics + screenshot paths
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


_IMPORT_RE = re.compile(
    r"^\s*(import\s+paraview|from\s+paraview\b)", re.MULTILINE,
)
_USAGE_RE = re.compile(
    r"\b(?:paraview\.simple|pvs?)\."
    r"(?:OpenDataFile|Sphere|Cone|Slice|Clip|Contour|Threshold|Calculator|"
    r"Show|Hide|Render|SaveScreenshot|SaveData|ColorBy|"
    r"GetActiveSource|GetActiveView|ResetCamera|Connect|"
    r"StreamTracer|IntegrateVariables|PlotOverLine|"
    r"CreateRenderView|GetRepresentation|UpdatePipeline)",
)

# ParaView version extraction from --version output.
# Typical: "paraview version 5.13.0" or "5.13.0"
_VERSION_RE = re.compile(r"(\d+\.\d+(?:\.\d+)?)")

# Known Windows install roots (Kitware uses Program Files)
_WIN_ROOTS = [
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")),
    Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")),
]

# Known Linux/macOS install roots
_UNIX_ROOTS = [Path("/opt"), Path("/usr/local"), Path.home() / "ParaView"]


def _probe_pvpython(exe: Path) -> str | None:
    """Run pvpython --version and return the version string, or None."""
    if not exe.is_file():
        return None
    try:
        proc = subprocess.run(
            [str(exe), "--version"],
            capture_output=True, text=True, timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    # pvpython --version may return on stdout or stderr
    text = (proc.stdout or "") + (proc.stderr or "")
    m = _VERSION_RE.search(text)
    return m.group(1) if m else None


def _probe_python_for_paraview(python_exe: Path) -> str | None:
    """Check if a Python interpreter has paraview importable (conda install)."""
    if not python_exe.is_file():
        return None
    try:
        proc = subprocess.run(
            [str(python_exe), "-c",
             "import paraview; print(paraview.__version__)"],
            capture_output=True, text=True, timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    return (proc.stdout or "").strip() or None


def _scan_paraview_installs() -> list[tuple[str, Path, str]]:
    """Scan filesystem for ParaView binary installs.

    Returns list of (version, pvpython_path, source).
    """
    results: list[tuple[str, Path, str]] = []

    # 1. PATH search for pvpython / pvbatch
    for name in ("pvpython", "pvbatch"):
        p = shutil.which(name)
        if p:
            path = Path(p)
            ver = _probe_pvpython(path)
            if ver:
                results.append((ver, path, f"which:{name}"))

    # 2. Environment variable: PV_HOME, PARAVIEW_HOME
    for var in ("PV_HOME", "PARAVIEW_HOME"):
        val = os.environ.get(var)
        if not val:
            continue
        root = Path(val)
        for candidate in _pvpython_candidates(root):
            ver = _probe_pvpython(candidate)
            if ver:
                results.append((ver, candidate, f"env:{var}"))
                break

    # 3. Scan known install directories
    if os.name == "nt":
        roots = _WIN_ROOTS
    else:
        roots = _UNIX_ROOTS

    for base in roots:
        if not base.is_dir():
            continue
        try:
            for child in base.iterdir():
                if not child.name.lower().startswith("paraview"):
                    continue
                for candidate in _pvpython_candidates(child):
                    ver = _probe_pvpython(candidate)
                    if ver:
                        results.append((ver, candidate, f"scan:{base}"))
                        break
        except PermissionError:
            continue

    return results


def _pvpython_candidates(root: Path) -> list[Path]:
    """Given a ParaView install root, return candidate pvpython paths."""
    candidates = []
    if os.name == "nt":
        candidates = [
            root / "bin" / "pvpython.exe",
            root / "pvpython.exe",
        ]
    else:
        candidates = [
            root / "bin" / "pvpython",
            root / "pvpython",
        ]
    return [c for c in candidates if c.exists()]


class ParaViewDriver:
    """Sim driver for ParaView (Kitware visualization platform)."""

    @property
    def name(self) -> str:
        return "paraview"

    @property
    def supports_session(self) -> bool:
        return False  # Phase 1: one-shot via pvpython/pvbatch

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

        if not text.strip():
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(level="error", message="Script is empty")],
            )

        if not _IMPORT_RE.search(text):
            diagnostics.append(Diagnostic(
                level="error",
                message="No `import paraview` / `from paraview` found",
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
                    "No paraview.simple API call found "
                    "(OpenDataFile/Show/Render/SaveScreenshot/etc.) "
                    "-- script may not do anything"
                ),
            ))

        # Check for interactive patterns that won't work in batch
        if re.search(r"\bInteract\s*\(", text):
            diagnostics.append(Diagnostic(
                level="warning",
                message="Interact() blocks indefinitely in batch mode -- remove for sim",
            ))

        ok = not any(d.level == "error" for d in diagnostics)
        return LintResult(ok=ok, diagnostics=diagnostics)

    def connect(self) -> ConnectionInfo:
        installs = self.detect_installed()
        if not installs:
            return ConnectionInfo(
                solver="paraview", version=None, status="not_installed",
                message=(
                    "ParaView not found. Install via conda "
                    "(conda install conda-forge::paraview) or download from "
                    "paraview.org and ensure pvpython is on PATH."
                ),
            )
        top = installs[0]
        return ConnectionInfo(
            solver="paraview", version=top.version, status="ok",
            message=f"ParaView {top.version} at {top.path}",
            solver_version=top.version,
        )

    def detect_installed(self) -> list[SolverInstall]:
        found: dict[str, SolverInstall] = {}

        def _record(exe: Path, version: str, source: str,
                     is_pvpython: bool = True) -> None:
            key = str(exe.resolve())
            if key in found:
                return
            short = ".".join(version.split(".")[:2])
            extra: dict = {"raw_version": version}
            if is_pvpython:
                extra["pvpython"] = str(exe)
                # Derive pvbatch from pvpython location
                pvbatch = exe.parent / (
                    "pvbatch.exe" if os.name == "nt" else "pvbatch"
                )
                if pvbatch.is_file():
                    extra["pvbatch"] = str(pvbatch)
            else:
                extra["python"] = str(exe)

            found[key] = SolverInstall(
                name="paraview", version=short,
                path=str(exe.parent), source=source,
                extra=extra,
            )

        # 1. Binary installs (pvpython on PATH or known locations)
        for ver, pvpy, source in _scan_paraview_installs():
            _record(pvpy, ver, source, is_pvpython=True)

        # 2. Conda/pip paraview in current Python env
        ver = _probe_python_for_paraview(Path(sys.executable))
        if ver:
            _record(Path(sys.executable), ver, "sys.executable",
                    is_pvpython=False)

        # 3. Other Python interpreters on PATH
        for name in ("python3", "python"):
            p = shutil.which(name)
            if p and str(Path(p).resolve()) != str(Path(sys.executable).resolve()):
                ver = _probe_python_for_paraview(Path(p))
                if ver:
                    _record(Path(p), ver, f"which:{name}",
                            is_pvpython=False)

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
                f"ParaView driver only accepts .py scripts (got {script.suffix})"
            )
        installs = self.detect_installed()
        if not installs:
            raise RuntimeError(
                "ParaView is not installed. Install via conda "
                "(conda install conda-forge::paraview) or download from "
                "paraview.org and ensure pvpython is on PATH."
            )
        top = installs[0]
        # Prefer pvpython (has full ParaView bindings); fall back to
        # regular python (conda install)
        exe = top.extra.get("pvpython") or top.extra.get("python", sys.executable)
        return run_subprocess(
            [exe, str(script)], script=script, solver=self.name,
        )

    # Session lifecycle stubs — one-shot driver, but DriverProtocol is
    # runtime_checkable so every method must exist. See `sim.driver`.
    def launch(self, **kwargs) -> dict:
        raise NotImplementedError(f"{self.name} driver does not support sessions")

    def run(self, code: str, label: str = "") -> dict:
        raise NotImplementedError(f"{self.name} driver does not support sessions")

    def disconnect(self) -> dict:
        return {"ok": True, "disconnected": True}
