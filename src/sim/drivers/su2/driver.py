"""SU2 driver for sim.

SU2 is an open-source multi-physics PDE solver suite (primary focus CFD)
from Stanford. The solver binary is SU2_CFD; a case is defined by:
    <case>.cfg  — config file (key=value plain text, comments start with %)
    <mesh>.su2  — mesh file referenced via MESH_FILENAME=

Execution: ``SU2_CFD config.cfg``. Output files land in cwd:
    history.csv         — per-iteration convergence history
    restart_flow.dat    — binary restart
    flow.vtu            — volume VTK for ParaView
    surface_flow.vtu    — surface VTK

This driver runs a single serial SU2_CFD invocation (no MPI). MPI / SLURM
orchestration is a future extension.
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


_CFG_KEYWORD_RE = re.compile(
    r"^\s*(SOLVER|MATH_PROBLEM|MESH_FILENAME|MACH_NUMBER|MARKER_\w+|ITER|CFL_NUMBER)\s*=",
    re.MULTILINE | re.IGNORECASE,
)
_SOLVER_RE = re.compile(r"^\s*SOLVER\s*=\s*\w+", re.MULTILINE | re.IGNORECASE)
_MESH_RE = re.compile(r"^\s*MESH_FILENAME\s*=", re.MULTILINE | re.IGNORECASE)
_MARKER_RE = re.compile(r"^\s*MARKER_\w+\s*=", re.MULTILINE | re.IGNORECASE)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def _version_from_cfd(cfd_bin: Path) -> str | None:
    """Extract version from `SU2_CFD --help` banner: 'SU2 v8.4.0 ...'."""
    try:
        proc = subprocess.run(
            [str(cfd_bin), "--help"],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    out = (proc.stdout or "") + (proc.stderr or "")
    m = re.search(r"SU2\s+v?(\d+\.\d+(?:\.\d+)?)", out, re.IGNORECASE)
    return m.group(1) if m else None


def _make_install(cfd_bin: Path, source: str) -> SolverInstall | None:
    if not cfd_bin.is_file():
        return None
    version = _version_from_cfd(cfd_bin)
    if version is None:
        return None
    short = ".".join(version.split(".")[:2])
    return SolverInstall(
        name="su2", version=short,
        path=str(cfd_bin.parent), source=source,
        extra={"bin": str(cfd_bin), "raw_version": version},
    )


def _candidates_from_env() -> list[tuple[Path, str]]:
    out = []
    for var in ("SU2_HOME", "SU2_RUN"):
        val = os.environ.get(var)
        if not val:
            continue
        p = Path(val)
        if p.is_file():
            out.append((p, f"env:{var}"))
        elif p.is_dir():
            for name in ("SU2_CFD",):
                cand = p / "bin" / name
                if cand.is_file():
                    out.append((cand, f"env:{var}"))
                cand = p / name
                if cand.is_file():
                    out.append((cand, f"env:{var}"))
    return out


def _candidates_from_default() -> list[tuple[Path, str]]:
    bases = [
        Path("/data/Chenyx/sim/opt/su2/bin"),
        Path("/opt/su2/bin"),
        Path("/usr/local/su2/bin"),
    ]
    out = []
    for base in bases:
        cand = base / "SU2_CFD"
        if cand.is_file():
            out.append((cand, f"default-path:{base}"))
    return out


def _candidates_from_path() -> list[tuple[Path, str]]:
    out = []
    cand = shutil.which("SU2_CFD")
    if cand:
        out.append((Path(cand).resolve(), "which:SU2_CFD"))
    return out


_FINDERS = [_candidates_from_env, _candidates_from_default, _candidates_from_path]


def _scan_su2_installs() -> list[SolverInstall]:
    found: dict[str, SolverInstall] = {}
    for finder in _FINDERS:
        try:
            candidates = finder()
        except Exception:
            continue
        for cfd_bin, source in candidates:
            key = str(cfd_bin.resolve())
            if key in found:
                continue
            inst = _make_install(cfd_bin, source)
            if inst is not None:
                found[key] = inst
    return sorted(found.values(), key=lambda i: i.version, reverse=True)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


class Su2Driver:
    """Sim driver for SU2 (open-source CFD/multi-physics solver)."""

    @property
    def name(self) -> str:
        return "su2"

    @property
    def supports_session(self) -> bool:
        return False

    def detect(self, script: Path) -> bool:
        try:
            if script.suffix.lower() != ".cfg":
                return False
            text = script.read_text(encoding="utf-8", errors="replace")
            return bool(_CFG_KEYWORD_RE.search(text))
        except (OSError, UnicodeDecodeError):
            return False

    def lint(self, script: Path) -> LintResult:
        diagnostics: list[Diagnostic] = []
        if script.suffix.lower() != ".cfg":
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(
                    level="error",
                    message=f"Unsupported file type: {script.suffix} (expected .cfg)",
                )],
            )
        try:
            text = script.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(level="error", message=f"Cannot read: {e}")],
            )

        if not _SOLVER_RE.search(text):
            diagnostics.append(Diagnostic(
                level="error",
                message="No SOLVER= line — SU2 cannot determine the physics type",
            ))
        if not _MESH_RE.search(text):
            diagnostics.append(Diagnostic(
                level="error",
                message="No MESH_FILENAME= line — SU2 needs a mesh file reference",
            ))
        if not _MARKER_RE.search(text):
            diagnostics.append(Diagnostic(
                level="warning",
                message="No MARKER_* lines — boundary conditions likely missing",
            ))

        ok = not any(d.level == "error" for d in diagnostics)
        return LintResult(ok=ok, diagnostics=diagnostics)

    def connect(self) -> ConnectionInfo:
        installs = self.detect_installed()
        if not installs:
            return ConnectionInfo(
                solver="su2", version=None, status="not_installed",
                message="SU2_CFD binary not found",
            )
        top = installs[0]
        return ConnectionInfo(
            solver="su2", version=top.version, status="ok",
            message=f"SU2 {top.extra.get('raw_version', top.version)} at {top.path}",
            solver_version=top.version,
        )

    def detect_installed(self) -> list[SolverInstall]:
        return _scan_su2_installs()

    def parse_output(self, stdout: str) -> dict:
        for line in reversed(stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        return {}

    def run_file(self, script: Path) -> RunResult:
        installs = self.detect_installed()
        if not installs:
            raise RuntimeError("SU2 is not installed on this host")
        if script.suffix.lower() != ".cfg":
            raise RuntimeError(f"SU2 only accepts .cfg config files (got {script.suffix})")

        cfd_bin = installs[0].extra.get("bin", "SU2_CFD")
        work_dir = script.parent

        start = time.monotonic()
        try:
            proc = subprocess.run(
                [cfd_bin, script.name],
                capture_output=True, text=True,
                cwd=str(work_dir), timeout=1800,
            )
        except subprocess.TimeoutExpired:
            return RunResult(
                exit_code=-1, stdout="",
                stderr="SU2_CFD timed out after 1800s",
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
