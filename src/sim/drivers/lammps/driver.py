"""LAMMPS driver for sim.

LAMMPS (Large-scale Atomic/Molecular Massively Parallel Simulator) is an
open-source classical MD code by Sandia/Temple. Input is a plain-text
script of LAMMPS commands (`.in` or `.lmp` file). Execution:

    lmp -in script.in

Output files in cwd:
    log.lammps          — simulation log (thermo, run info)
    dump.*              — trajectory (if `dump` command present)
    restart.*           — restart files (if `write_restart`)

This driver is pure subprocess — the lammps Python module is NOT imported
into the sim process (conda/pip wheels have MPI library requirements).
"""
from __future__ import annotations

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


_LAMMPS_KEYWORDS_RE = re.compile(
    r"^\s*(units|atom_style|dimension|boundary|lattice|region|create_box|"
    r"create_atoms|mass|velocity|pair_style|pair_coeff|fix|thermo|run|"
    r"read_data|minimize|dump|write_data|write_restart|reset_timestep|"
    r"compute|variable|neighbor|neigh_modify|timestep)\b",
    re.MULTILINE | re.IGNORECASE,
)
_UNITS_RE = re.compile(r"^\s*units\s+\w+", re.MULTILINE | re.IGNORECASE)
_ATOM_STYLE_RE = re.compile(r"^\s*atom_style\s+\w+", re.MULTILINE | re.IGNORECASE)
_RUN_RE = re.compile(r"^\s*(run|minimize|rerun)\b", re.MULTILINE | re.IGNORECASE)


def _version_from_lmp(lmp_bin: Path) -> str | None:
    """Extract version date from `lmp -h`: first line 'LAMMPS (24 Aug 2023)'."""
    try:
        proc = subprocess.run(
            [str(lmp_bin), "-h"],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    out = (proc.stdout or "") + (proc.stderr or "")
    # Historical banner: "LAMMPS (29 Aug 2023)"
    m = re.search(r"LAMMPS\s*\(([^)]+)\)", out)
    if m:
        return m.group(1).strip()
    # New banner (stable_29Aug2024): "Large-scale ... - 29 Aug 2024"
    m = re.search(r"-\s+(\d{1,2}\s+\w+\s+\d{4})", out)
    return m.group(1).strip() if m else None


def _normalize_version(raw: str) -> str:
    """Turn '24 Aug 2023' into '20230824' (YYYYMMDD short form)."""
    if not raw:
        return "unknown"
    m = re.match(r"(\d+)\s+(\w+)\s+(\d{4})", raw)
    if not m:
        return raw
    months = {"jan":"01","feb":"02","mar":"03","apr":"04","may":"05","jun":"06",
              "jul":"07","aug":"08","sep":"09","oct":"10","nov":"11","dec":"12"}
    day = m.group(1).zfill(2)
    mon = months.get(m.group(2).lower()[:3], "00")
    year = m.group(3)
    return f"{year}{mon}{day}"


def _make_install(lmp_bin: Path, source: str) -> SolverInstall | None:
    if not lmp_bin.is_file():
        return None
    raw = _version_from_lmp(lmp_bin)
    if raw is None:
        return None
    short = _normalize_version(raw)
    return SolverInstall(
        name="lammps", version=short,
        path=str(lmp_bin.parent), source=source,
        extra={"bin": str(lmp_bin), "raw_version": raw},
    )


def _candidates_from_env() -> list[tuple[Path, str]]:
    out = []
    for var in ("LAMMPS_BIN", "LAMMPS_HOME"):
        val = os.environ.get(var)
        if not val:
            continue
        p = Path(val)
        if p.is_file():
            out.append((p, f"env:{var}"))
        elif p.is_dir():
            for name in ("lmp", "lmp_serial", "lmp_mpi"):
                cand = p / "bin" / name
                if cand.is_file():
                    out.append((cand, f"env:{var}"))
    return out


def _candidates_from_venv() -> list[tuple[Path, str]]:
    """Check the interpreter's venv bin dir — conda/pip installs live here."""
    bindir = Path(sys.executable).parent
    out = []
    for name in ("lmp", "lmp_serial", "lmp_mpi"):
        cand = bindir / name
        if cand.is_file():
            out.append((cand, "sys.executable"))
    return out


def _candidates_from_default() -> list[tuple[Path, str]]:
    bases = [
        Path("/data/Chenyx/sim/opt/lammps"),
        Path("/data/Chenyx/sim/opt/lammps/bin"),
        Path("/data/Chenyx/sim/opt/lammps/src"),
        Path("/opt/lammps/bin"),
        Path("/usr/bin"),
        Path("/usr/local/bin"),
    ]
    out = []
    for base in bases:
        for name in ("lmp", "lmp_serial", "lmp_mpi"):
            cand = base / name
            if cand.is_file():
                out.append((cand, f"default-path:{base}"))
    return out


def _candidates_from_path() -> list[tuple[Path, str]]:
    out = []
    for name in ("lmp", "lmp_serial", "lmp_mpi"):
        p = shutil.which(name)
        if p:
            out.append((Path(p).resolve(), f"which:{name}"))
    return out


_FINDERS = [_candidates_from_env, _candidates_from_venv,
            _candidates_from_default, _candidates_from_path]


def _scan_lammps_installs() -> list[SolverInstall]:
    found: dict[str, SolverInstall] = {}
    for finder in _FINDERS:
        try:
            cands = finder()
        except Exception:
            continue
        for b, s in cands:
            key = str(b.resolve())
            if key in found:
                continue
            inst = _make_install(b, s)
            if inst is not None:
                found[key] = inst
    return sorted(found.values(), key=lambda i: i.version, reverse=True)


class LammpsDriver:
    """Sim driver for LAMMPS (classical molecular dynamics)."""

    @property
    def name(self) -> str:
        return "lammps"

    @property
    def supports_session(self) -> bool:
        return False

    def detect(self, script: Path) -> bool:
        try:
            if script.suffix.lower() not in (".in", ".lmp"):
                return False
            text = script.read_text(encoding="utf-8", errors="replace")
            return bool(_LAMMPS_KEYWORDS_RE.search(text))
        except (OSError, UnicodeDecodeError):
            return False

    def lint(self, script: Path) -> LintResult:
        diagnostics: list[Diagnostic] = []
        if script.suffix.lower() not in (".in", ".lmp"):
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(
                    level="error",
                    message=f"Unsupported file type: {script.suffix} (expected .in or .lmp)",
                )],
            )
        try:
            text = script.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(level="error", message=f"Cannot read: {e}")],
            )

        if not _UNITS_RE.search(text):
            diagnostics.append(Diagnostic(
                level="error",
                message="No `units` command — required before anything else",
            ))
        if not _ATOM_STYLE_RE.search(text):
            diagnostics.append(Diagnostic(
                level="error",
                message="No `atom_style` command — required",
            ))
        if not _RUN_RE.search(text):
            diagnostics.append(Diagnostic(
                level="warning",
                message="No `run` / `minimize` command — simulation won't do anything",
            ))

        ok = not any(d.level == "error" for d in diagnostics)
        return LintResult(ok=ok, diagnostics=diagnostics)

    def connect(self) -> ConnectionInfo:
        installs = self.detect_installed()
        if not installs:
            return ConnectionInfo(
                solver="lammps", version=None, status="not_installed",
                message="lmp binary not found",
            )
        top = installs[0]
        return ConnectionInfo(
            solver="lammps", version=top.version, status="ok",
            message=f"LAMMPS {top.extra.get('raw_version', top.version)} at {top.path}",
            solver_version=top.version,
        )

    def detect_installed(self) -> list[SolverInstall]:
        return _scan_lammps_installs()

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
            raise RuntimeError("LAMMPS is not installed on this host")
        if script.suffix.lower() not in (".in", ".lmp"):
            raise RuntimeError(f"LAMMPS only accepts .in/.lmp (got {script.suffix})")

        lmp_bin = installs[0].extra.get("bin", "lmp")
        work_dir = script.parent

        start = time.monotonic()
        try:
            proc = subprocess.run(
                [lmp_bin, "-in", script.name],
                capture_output=True, text=True,
                cwd=str(work_dir), timeout=1800,
            )
        except subprocess.TimeoutExpired:
            return RunResult(
                exit_code=-1, stdout="",
                stderr="LAMMPS timed out after 1800s",
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
