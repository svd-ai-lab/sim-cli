"""HyperMesh driver for sim.

Altair HyperMesh is a high-performance FE pre-processor for meshing,
model setup, and solver deck generation. Used as sim's heavyweight
meshing and model-building tool for crash, NVH, durability, and CFD
pre-processing.

Execution model:
  GUI + script: runhwx.exe ... -startwith HyperMesh -f script.py
  The `hm` module requires a fully initialized HyperMesh session
  (Create Session in the Launcher). The -f flag auto-executes the
  script once the session is ready. Headless batch (-b) does NOT
  initialize HyperMesh and cannot import hm.
  Tcl-only batch: hmbatch.exe -tcl script.tcl (no Python API)

Scripts use the `hm` Python API:
    import hm
    import hm.entities as ent
    model = hm.Model()

Typical agent workflow:
    1. Import CAD geometry (STEP/IGES/CATIA/NX)
    2. Create materials/properties
    3. Generate mesh (automesh/tetmesh/batchmesh)
    4. Run quality checks (aspect ratio, jacobian, skew)
    5. Export solver deck (OptiStruct/Nastran/Abaqus/LS-DYNA)
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
    r"^\s*(import\s+hm\b|from\s+hm\b)", re.MULTILINE,
)
_USAGE_RE = re.compile(
    r"\bhm\.(Model|Collection|Session|FilterBy|setoption|"
    r"CollectionBy|EntityBy)|"
    r"\bent\.(Node|Element|Material|Property|Component|"
    r"LoadForce|LoadConstraint|Surface|Solid)",
)
_GUI_RE = re.compile(
    r"\b(CollectionByInteractiveSelection|EntityByInteractiveSelection|"
    r"EntityListByInteractiveSelection|PlaneByInteractiveSelection)\b",
)

# HyperMesh version extraction
_VERSION_RE = re.compile(r"(\d{4}(?:\.\d+)*)")

# Known Windows install patterns
_WIN_ROOTS = [
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")),
    Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")),
]


def _find_runhwx(root: Path) -> Path | None:
    """Find runhwx.exe (HyperWorks launcher) under an Altair install root."""
    # HyperWorks 2026: <root>/hwdesktop/hwx/bin/win64/runhwx.exe
    candidates = [
        root / "hwdesktop" / "hwx" / "bin" / "win64" / "runhwx.exe",
        root / "hwdesktop" / "hwx" / "bin" / "linux64" / "runhwx",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def _find_hmbatch(root: Path) -> Path | None:
    """Find hmbatch.exe (Tcl-only batch) under an Altair install root."""
    candidates = [
        root / "hwdesktop" / "hw" / "bin" / "win64" / "hmbatch.exe",
        root / "hwdesktop" / "hw" / "bin" / "linux64" / "hmbatch",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def _probe_hw_version(exe: Path) -> str | None:
    """Try to determine HyperMesh version from the install path or exe."""
    # Version is typically in the path: .../Altair/2025/...
    for part in exe.parts:
        m = _VERSION_RE.match(part)
        if m:
            return m.group(1)
    # Try running hw --version (may not be supported in all versions)
    try:
        proc = subprocess.run(
            [str(exe), "--version"],
            capture_output=True, text=True, timeout=15,
        )
        text = (proc.stdout or "") + (proc.stderr or "")
        m = _VERSION_RE.search(text)
        if m:
            return m.group(1)
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def _scan_altair_installs() -> list[tuple[str, Path, str]]:
    """Scan for Altair HyperMesh installations.

    Returns list of (version, hw_exe_path, source).
    """
    results: list[tuple[str, Path, str]] = []

    def _try_root(root: Path, source: str) -> None:
        runhwx = _find_runhwx(root)
        hmbatch = _find_hmbatch(root)
        exe = runhwx or hmbatch
        if not exe:
            return
        ver = _probe_hw_version(exe)
        if ver:
            extra: dict = {"raw_version": ver}
            if runhwx:
                extra["runhwx"] = str(runhwx)
            if hmbatch:
                extra["hmbatch"] = str(hmbatch)
            results.append((ver, exe, source))

    # 1. ALTAIR_HOME environment variable
    altair_home = os.environ.get("ALTAIR_HOME")
    if altair_home:
        _try_root(Path(altair_home), "env:ALTAIR_HOME")

    # 2. PATH search for runhwx / hmbatch
    for name in ("runhwx", "hmbatch", "runhwx.exe", "hmbatch.exe"):
        p = shutil.which(name)
        if p:
            path = Path(p)
            ver = _probe_hw_version(path)
            if ver:
                results.append((ver, path, f"which:{name}"))

    # 3. Scan known install directories
    if os.name == "nt":
        scan_roots = _WIN_ROOTS
    else:
        scan_roots = [Path("/opt"), Path("/usr/local")]

    for base in scan_roots:
        if not base.is_dir():
            continue
        try:
            for child in base.iterdir():
                if not child.name.lower().startswith("altair"):
                    continue
                # Check direct: Altair/2026/...
                _try_root(child, f"scan:{base}")
                # Check versioned subdirs: Altair/2026/hwdesktop/...
                try:
                    for verdir in child.iterdir():
                        if verdir.is_dir() and _VERSION_RE.match(verdir.name):
                            _try_root(verdir, f"scan:{base}")
                except PermissionError:
                    continue
        except PermissionError:
            continue

    return results


class HyperMeshDriver:
    """Sim driver for Altair HyperMesh (FE pre-processor)."""

    @property
    def name(self) -> str:
        return "hypermesh"

    @property
    def supports_session(self) -> bool:
        return False  # One-shot batch mode

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
                message="No `import hm` / `from hm` found",
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
                    "No hm.Model/Collection/entities usage found "
                    "-- script may not do anything"
                ),
            ))

        # Check for interactive GUI patterns that won't work in batch
        gui_match = _GUI_RE.search(text)
        if gui_match:
            diagnostics.append(Diagnostic(
                level="warning",
                message=(
                    f"{gui_match.group(1)}() requires GUI interaction "
                    "-- will fail in batch mode (-b)"
                ),
            ))

        ok = not any(d.level == "error" for d in diagnostics)
        return LintResult(ok=ok, diagnostics=diagnostics)

    def connect(self) -> ConnectionInfo:
        installs = self.detect_installed()
        if not installs:
            return ConnectionInfo(
                solver="hypermesh", version=None, status="not_installed",
                message=(
                    "HyperMesh not found. Install Altair HyperWorks Desktop "
                    "and ensure ALTAIR_HOME is set or hw/hmbatch is on PATH."
                ),
            )
        top = installs[0]
        return ConnectionInfo(
            solver="hypermesh", version=top.version, status="ok",
            message=f"HyperMesh {top.version} at {top.path}",
            solver_version=top.version,
        )

    def detect_installed(self) -> list[SolverInstall]:
        found: dict[str, SolverInstall] = {}

        for ver, exe, source in _scan_altair_installs():
            key = str(exe.resolve())
            if key in found:
                continue
            # Derive runhwx and hmbatch from install root
            # exe could be either runhwx or hmbatch
            install_root = exe
            for _ in range(6):  # walk up to Altair/<ver>
                install_root = install_root.parent
                if _VERSION_RE.match(install_root.name):
                    break
            extra: dict = {"raw_version": ver}
            runhwx = _find_runhwx(install_root)
            hmbatch = _find_hmbatch(install_root)
            if runhwx:
                extra["runhwx"] = str(runhwx)
            if hmbatch:
                extra["hmbatch"] = str(hmbatch)

            found[key] = SolverInstall(
                name="hypermesh", version=ver,
                path=str(install_root), source=source,
                extra=extra,
            )

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
                f"HyperMesh driver only accepts .py scripts (got {script.suffix})"
            )
        installs = self.detect_installed()
        if not installs:
            raise RuntimeError(
                "HyperMesh is not installed. Install Altair HyperWorks Desktop "
                "and ensure ALTAIR_HOME is set or runhwx/hmbatch is on PATH."
            )
        top = installs[0]
        runhwx = top.extra.get("runhwx")
        hmbatch = top.extra.get("hmbatch")

        if runhwx:
            # Python scripts via runhwx.exe (requires GUI session).
            # runhwx launches HyperWorks Desktop with the Launcher;
            # -startwith HyperMesh auto-selects the HyperMesh profile;
            # -f <script> auto-executes the script once the session
            # is initialized (user must Create Session first).
            cmd = [
                runhwx,
                "-client", "HyperWorksDesktop",
                "-plugin", "HyperworksLauncher",
                "-profile", "HyperworksLauncher",
                "-l", "en",
                "-startwith", "HyperMesh",
                "-f", str(script),
            ]
        elif hmbatch:
            # Tcl-only fallback — cannot import hm Python API.
            # Only works for .tcl scripts; .py will fail.
            raise RuntimeError(
                "Only hmbatch (Tcl) found — Python scripts require "
                "runhwx.exe (HyperWorks Desktop). The hm Python API "
                "needs a fully initialized HyperMesh GUI session."
            )
        else:
            raise RuntimeError("No HyperMesh executable found.")

        return run_subprocess(cmd, script=script, solver=self.name)
