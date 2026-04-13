"""LS-DYNA driver for sim.

LS-DYNA is an explicit/implicit FEA solver by Ansys (formerly LSTC).
Execution is via the ``lsdyna`` command-line tool:
  - Keyword files (.k / .key / .dyn): ``lsdyna_sp.exe i=<file>``

This driver is pure subprocess — it never imports LS-DYNA internals.
Detection scans for lsdyna executables in standard ANSYS install paths.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from sim.driver import ConnectionInfo, Diagnostic, LintResult, RunResult, SolverInstall

# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------

_KEYWORD_EXTENSIONS = {".k", ".key", ".dyn"}

_KEYWORD_MARKER_RE = re.compile(r"^\*KEYWORD\b", re.MULTILINE)

# LS-DYNA output patterns for parse_output
_NORMAL_TERM_RE = re.compile(
    r"N\s*o\s*r\s*m\s*a\s*l\s+t\s*e\s*r\s*m\s*i\s*n\s*a\s*t\s*i\s*o\s*n"
)
_ERROR_TERM_RE = re.compile(r"E\s*r\s*r\s*o\s*r\s+t\s*e\s*r\s*m\s*i\s*n\s*a\s*t\s*i\s*o\s*n")
_ELAPSED_RE = re.compile(r"Elapsed\s+time\s+([\d.]+)\s+seconds", re.IGNORECASE)
_ERROR_PATTERN_RE = re.compile(r"\*\*\*\s*(Error|Fatal)", re.IGNORECASE)

# Executables to search for (preferred order: sp first for speed in testing)
_EXE_NAMES = [
    "lsdyna_sp.exe",
    "lsdyna_dp.exe",
    "LSDYNA.exe",
    "lsdyna_mpp_sp_impi.exe",
    "lsdyna_mpp_dp_impi.exe",
    "lsdyna_mpp_sp_msmpi.exe",
    "lsdyna_mpp_dp_msmpi.exe",
]

# Also check Linux names
_EXE_NAMES_LINUX = [
    "lsdyna_sp",
    "lsdyna_dp",
    "ls-dyna_smp_s",
    "ls-dyna_smp_d",
    "ls-dyna_mpp_d",
]


# ---------------------------------------------------------------------------
# Install-dir finders (strategy chain)
# ---------------------------------------------------------------------------


def _candidates_from_env() -> list[tuple[Path, str]]:
    """Check LSTC_LICENSE_FILE, AWP_ROOT241 and similar env vars."""
    out: list[tuple[Path, str]] = []
    # AWP_ROOTnnn is set by Ansys installations
    for var, val in os.environ.items():
        if var.startswith("AWP_ROOT"):
            p = Path(val) / "ansys" / "bin" / "winx64"
            if p.is_dir():
                out.append((p, f"env:{var}"))
    # Direct LSDYNA path
    for var in ("LSDYNA_HOME", "LS_DYNA_PATH"):
        val = os.environ.get(var)
        if val:
            p = Path(val)
            if p.is_dir():
                out.append((p, f"env:{var}"))
    return out


def _candidates_from_defaults() -> list[tuple[Path, str]]:
    """Scan standard ANSYS install directories on Windows."""
    out: list[tuple[Path, str]] = []
    for drive in ("C", "D", "E"):
        # Ansys v24x installs
        base = Path(f"{drive}:/Program Files/ANSYS Inc")
        if base.is_dir():
            try:
                for ver_dir in sorted(base.iterdir(), reverse=True):
                    bin_dir = ver_dir / "ansys" / "bin" / "winx64"
                    if bin_dir.is_dir():
                        out.append((bin_dir, f"default-path:{bin_dir}"))
            except OSError:
                pass
    return out


def _candidates_from_path() -> list[tuple[Path, str]]:
    """``which lsdyna`` — last-resort PATH probe."""
    out: list[tuple[Path, str]] = []
    for name in ["lsdyna_sp", "lsdyna_dp", "LSDYNA", "lsdyna"]:
        found = shutil.which(name)
        if found:
            p = Path(found).resolve()
            out.append((p.parent, f"which:{name}"))
    return out


_INSTALL_FINDERS = [
    _candidates_from_env,
    _candidates_from_defaults,
    _candidates_from_path,
]


def _find_lsdyna_exe(bin_dir: Path) -> Path | None:
    """Find the best LS-DYNA executable in a directory."""
    names = _EXE_NAMES if os.name == "nt" else _EXE_NAMES_LINUX
    for name in names:
        exe = bin_dir / name
        if exe.is_file():
            return exe
    return None


def _extract_version_from_path(bin_dir: Path) -> str:
    """Extract version from path like .../v241/ansys/bin/... -> R14.0."""
    path_str = str(bin_dir)
    m = re.search(r"v(\d)(\d)(\d)", path_str)
    if m:
        major, minor, patch = m.groups()
        return f"R{major}{minor}.{patch}"
    return "unknown"


def _scan_lsdyna_installs() -> list[SolverInstall]:
    """Find every LS-DYNA installation on this host."""
    found: dict[str, SolverInstall] = {}

    for finder in _INSTALL_FINDERS:
        try:
            candidates = finder()
        except Exception:
            continue
        for bin_dir, source in candidates:
            exe = _find_lsdyna_exe(bin_dir)
            if exe is None:
                continue

            key = str(exe.resolve())
            if key in found:
                continue

            version = _extract_version_from_path(bin_dir)
            found[key] = SolverInstall(
                name="ls_dyna",
                version=version,
                path=str(bin_dir),
                source=source,
                extra={"exe": str(exe)},
            )

    return sorted(found.values(), key=lambda i: i.version, reverse=True)


# ---------------------------------------------------------------------------
# Driver class
# ---------------------------------------------------------------------------


class LsDynaDriver:
    """Sim driver for Ansys LS-DYNA.

    DriverProtocol surface:
        name, detect, lint, connect, parse_output, run_file, detect_installed
    """

    @property
    def name(self) -> str:
        return "ls_dyna"

    @property
    def supports_session(self) -> bool:
        return False

    # -- detect ---------------------------------------------------------------

    def detect(self, script: Path) -> bool:
        """Detect LS-DYNA keyword files: .k / .key / .dyn with *KEYWORD marker."""
        try:
            if script.suffix.lower() not in _KEYWORD_EXTENSIONS:
                return False
            text = script.read_text(encoding="utf-8", errors="replace")
            return bool(_KEYWORD_MARKER_RE.search(text))
        except (OSError, UnicodeDecodeError):
            return False

    # -- lint -----------------------------------------------------------------

    def lint(self, script: Path) -> LintResult:
        """Validate an LS-DYNA keyword file."""
        diagnostics: list[Diagnostic] = []
        suffix = script.suffix.lower()

        if suffix not in _KEYWORD_EXTENSIONS:
            return LintResult(
                ok=False,
                diagnostics=[
                    Diagnostic(
                        level="error",
                        message=f"Unsupported file type: {suffix} (expected .k, .key, or .dyn)",
                    )
                ],
            )

        try:
            text = script.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(level="error", message=f"Cannot read file: {e}")],
            )

        # Check for *KEYWORD marker (required)
        if not _KEYWORD_MARKER_RE.search(text):
            diagnostics.append(
                Diagnostic(level="error", message="No *KEYWORD marker found — not a valid LS-DYNA keyword file")
            )

        # Check for *END (recommended)
        if not re.search(r"^\*END\b", text, re.MULTILINE):
            diagnostics.append(
                Diagnostic(level="warning", message="No *END keyword found — file may be incomplete")
            )

        # Check for *NODE (expected in most models)
        if not re.search(r"^\*NODE\b", text, re.MULTILINE):
            diagnostics.append(
                Diagnostic(level="warning", message="No *NODE section found — model has no node definitions")
            )

        # Check for *ELEMENT (expected in most models)
        if not re.search(r"^\*ELEMENT", text, re.MULTILINE):
            diagnostics.append(
                Diagnostic(level="warning", message="No *ELEMENT section found — model has no element definitions")
            )

        # Check for termination control
        if not re.search(r"^\*CONTROL_TERMINATION", text, re.MULTILINE):
            diagnostics.append(
                Diagnostic(level="warning", message="No *CONTROL_TERMINATION found — solver may run indefinitely")
            )

        ok = not any(d.level == "error" for d in diagnostics)
        return LintResult(ok=ok, diagnostics=diagnostics)

    # -- connect / detect_installed -------------------------------------------

    def connect(self) -> ConnectionInfo:
        """Lightweight availability check via detect_installed."""
        installs = self.detect_installed()
        if not installs:
            return ConnectionInfo(
                solver="ls_dyna",
                version=None,
                status="not_installed",
                message="No LS-DYNA installation detected on this host",
            )
        top = installs[0]
        return ConnectionInfo(
            solver="ls_dyna",
            version=top.version,
            status="ok",
            message=f"LS-DYNA {top.version} at {top.path}",
            solver_version=top.version,
        )

    def detect_installed(self) -> list[SolverInstall]:
        """Scan for LS-DYNA installations. Pure stdlib, no SDK import."""
        return _scan_lsdyna_installs()

    # -- runtime env ----------------------------------------------------------

    @staticmethod
    def _runtime_env(install: SolverInstall) -> dict[str, str]:
        """Build env-var overrides so LS-DYNA finds Intel runtime DLLs.

        ANSYS ships Intel compiler/MKL libs under ``<AWP_ROOT>/tp/``.
        Without them on PATH, lsdyna_sp.exe fails with "cannot open
        shared object file: libiomp5md.dll".
        """
        extra_paths: list[str] = []
        bin_dir = Path(install.path)

        # Walk up from .../ansys/bin/winx64 to the ANSYS root (v24x)
        awp_root = None
        for parent in [bin_dir] + list(bin_dir.parents):
            tp = parent / "tp"
            if tp.is_dir():
                awp_root = parent
                break

        if awp_root:
            # Intel Compiler runtime (libiomp5md.dll)
            intel_comp = awp_root / "tp" / "IntelCompiler"
            if intel_comp.is_dir():
                for ver in sorted(intel_comp.iterdir(), reverse=True):
                    winx64 = ver / "winx64"
                    if winx64.is_dir():
                        extra_paths.append(str(winx64))
                        break

            # Intel MKL
            intel_mkl = awp_root / "tp" / "IntelMKL"
            if intel_mkl.is_dir():
                for ver in sorted(intel_mkl.iterdir(), reverse=True):
                    winx64 = ver / "winx64"
                    if winx64.is_dir():
                        extra_paths.append(str(winx64))
                        break

        # Also add the bin dir itself
        extra_paths.append(str(bin_dir))

        env: dict[str, str] = {}
        if extra_paths:
            existing = os.environ.get("PATH", "")
            env["PATH"] = os.pathsep.join(extra_paths) + os.pathsep + existing

        return env

    # -- parse_output ---------------------------------------------------------

    def parse_output(self, stdout: str) -> dict:
        """Extract structured results from LS-DYNA solver output.

        Convention: scan from bottom for last JSON line.
        Also extract LS-DYNA-specific termination info.
        """
        # Try JSON first (driver convention)
        for line in reversed(stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue

        # Fall back to LS-DYNA output parsing
        result: dict = {}

        if _NORMAL_TERM_RE.search(stdout):
            result["termination"] = "normal"
        elif _ERROR_TERM_RE.search(stdout):
            result["termination"] = "error"

        m = _ELAPSED_RE.search(stdout)
        if m:
            result["elapsed_s"] = float(m.group(1))

        errors = _ERROR_PATTERN_RE.findall(stdout)
        if errors:
            result["errors"] = errors

        return result

    # -- run_file -------------------------------------------------------------

    def run_file(self, script: Path) -> RunResult:
        """Execute an LS-DYNA keyword file.

        Command: ``lsdyna i=<file>``

        LS-DYNA requires Intel runtime DLLs (libiomp5md.dll etc.) which
        live under the ANSYS tp/ tree. We augment PATH so the solver
        subprocess can find them.
        """
        installs = self.detect_installed()
        if not installs:
            raise RuntimeError("LS-DYNA is not installed on this host")

        exe = installs[0].extra.get("exe", "lsdyna_sp")
        work_dir = script.parent

        cmd = [exe, f"i={script.name}"]

        # Build environment with Intel runtime DLLs on PATH
        env = os.environ.copy()
        env.update(self._runtime_env(installs[0]))

        start = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(work_dir),
                timeout=600,
                env=env,
            )
        except subprocess.TimeoutExpired:
            duration = time.monotonic() - start
            return RunResult(
                exit_code=-1,
                stdout="",
                stderr="LS-DYNA execution timed out after 600s",
                duration_s=round(duration, 3),
                script=str(script),
                solver=self.name,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        duration = time.monotonic() - start

        stdout = proc.stdout.strip() if proc.stdout else ""
        stderr = proc.stderr.strip() if proc.stderr else ""

        # LS-DYNA also writes to d3hsp file — try to capture key info
        d3hsp = work_dir / "d3hsp"
        if d3hsp.is_file():
            try:
                hsp_text = d3hsp.read_text(encoding="utf-8", errors="replace")
                # Append termination status if not in stdout
                if "t e r m i n a t i o n" in hsp_text and "t e r m i n a t i o n" not in stdout:
                    # Find the termination line
                    for line in hsp_text.splitlines():
                        if "t e r m i n a t i o n" in line:
                            stdout = stdout + "\n" + line if stdout else line
                            break
            except OSError:
                pass

        return RunResult(
            exit_code=proc.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_s=round(duration, 3),
            script=str(script),
            solver=self.name,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
