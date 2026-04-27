"""Internal runtime helpers for the Flotherm driver.

Installation detection, process polling, and workspace state monitoring.
File-format / lint / FloSCRIPT generation moved to `sim.drivers.flotherm.lib`
so they can be unit-tested on macOS / Linux without Flotherm installed.

This module is not part of the public API — use FlothermDriver instead.
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
from contextlib import suppress
from pathlib import Path

from sim.drivers.flotherm.lib.error_log import (
    parse_error_log,
    parse_logfile_xml,
    read_floerror_log,
)

# ---------------------------------------------------------------------------
# Installation detection
# ---------------------------------------------------------------------------

_SCAN_DRIVES = ("C", "D", "E", "F", "G")


def find_installation() -> dict | None:
    """Locate Simcenter Flotherm installation.

    Returns {"bat_path", "floserv_path", "install_root", "version"} or None.

    Search order:
    1. FLOTHERM_ROOT environment variable
    2. System PATH (shutil.which "flotherm")
    3. Common install dirs on lettered drives (glob)
    """
    env_root = os.environ.get("FLOTHERM_ROOT", "").strip()
    if env_root:
        bat = os.path.join(env_root, "WinXP", "bin", "flotherm.bat")
        serv = os.path.join(env_root, "WinXP", "bin", "floserv.exe")
        if os.path.isfile(bat):
            version = extract_version(env_root) or "unknown"
            return {"bat_path": bat, "floserv_path": serv,
                    "install_root": env_root, "version": version}

    bat_on_path = shutil.which("flotherm")
    if bat_on_path:
        root = str(Path(bat_on_path).parent.parent.parent)
        serv = str(Path(bat_on_path).parent / "floserv.exe")
        version = extract_version(bat_on_path) or "unknown"
        return {"bat_path": bat_on_path, "floserv_path": serv,
                "install_root": root, "version": version}

    for drive in _SCAN_DRIVES:
        for prog_dir in (
            fr"{drive}:\Program Files (x86)\Siemens\SimcenterFlotherm",
            fr"{drive}:\Program Files\Siemens\SimcenterFlotherm",
            fr"{drive}:\Siemens\SimcenterFlotherm",
        ):
            pattern = os.path.join(prog_dir, "*", "WinXP", "bin", "flotherm.bat")
            matches = sorted(glob.glob(pattern), reverse=True)
            if matches:
                bat = matches[0]
                root = str(Path(bat).parent.parent.parent)
                serv = str(Path(bat).parent / "floserv.exe")
                version = extract_version(bat) or "unknown"
                return {"bat_path": bat, "floserv_path": serv,
                        "install_root": root, "version": version}

    return None


def extract_version(path: str) -> str | None:
    """Extract version number from path (e.g., '2504' from .../SimcenterFlotherm/2504/...)."""
    env_ver = os.environ.get("FLOTHERM_VERSION", "").strip()
    if env_ver:
        return env_ver
    m = re.search(r"SimcenterFlotherm[/\\](\d{4})", path, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"[/\\](\d{4})[/\\]", path)
    if m:
        return m.group(1)
    return None


def default_flouser(install_root: str) -> str:
    """Return the default FLOUSERDIR for an installation."""
    env = os.environ.get("FLOUSERDIR", "").strip()
    if env:
        return env
    return os.path.join(install_root, "flouser")


# ---------------------------------------------------------------------------
# GUI session log discovery (<install>/WinXP/bin/LogFiles/logFile*.xml)
# ---------------------------------------------------------------------------

def list_logfile_xmls(install_root: str) -> list[str]:
    """Return Flotherm GUI session log paths, newest first.

    Flotherm writes one `logFile<timestamp>.xml` per GUI session under
    `<install>/WinXP/bin/LogFiles/`, retaining up to 5. Sorted by file
    mtime descending so the first entry is the most recent session.
    Returns ``[]`` when the directory doesn't exist.
    """
    log_dir = os.path.join(install_root, "WinXP", "bin", "LogFiles")
    if not os.path.isdir(log_dir):
        return []
    candidates = []
    for name in os.listdir(log_dir):
        if name.startswith("logFile") and name.endswith(".xml"):
            full = os.path.join(log_dir, name)
            with suppress(OSError):
                candidates.append((os.path.getmtime(full), full))
    candidates.sort(reverse=True)
    return [path for _, path in candidates]


def tail_logfile_xml(
    install_root: str,
    *,
    most_recent_only: bool = True,
) -> list[dict]:
    """Return structured GUI-log entries under `<install>/WinXP/bin/LogFiles/`.

    Each entry is a plain dict ``{code, severity, message, suggested_action,
    raw}`` from :func:`sim.drivers.flotherm.lib.error_log.parse_logfile_xml`.

    With ``most_recent_only=True`` (default) reads only the most recently
    modified `logFile*.xml` — the typical "what just happened in this GUI
    session" use case. With ``most_recent_only=False`` merges every retained
    log file in newest-first order.

    Callers that want "only entries since a baseline" should pass the result
    through their own diff (the parser doesn't expose per-entry timestamps —
    use the same baseline-list approach the driver uses for `floerror.log`).
    """
    from dataclasses import asdict

    paths = list_logfile_xmls(install_root)
    if not paths:
        return []
    if most_recent_only:
        paths = paths[:1]
    out: list[dict] = []
    for p in paths:
        for entry in parse_logfile_xml(p):
            out.append(asdict(entry))
    return out


# ---------------------------------------------------------------------------
# Status detection (runtime polling against a live workspace)
# ---------------------------------------------------------------------------

FIELD_NAMES = (
    "Temperature", "Pressure", "Speed",
    "XVelocity", "YVelocity", "ZVelocity", "TurbVis",
)


def snapshot_result_files(field_dir: str) -> dict[str, float]:
    """Record modification times of field result files."""
    mtimes: dict[str, float] = {}
    if not os.path.isdir(field_dir):
        return mtimes
    for dirpath, _, filenames in os.walk(field_dir):
        for fn in filenames:
            if fn in FIELD_NAMES:
                fp = os.path.join(dirpath, fn)
                with suppress(OSError):
                    mtimes[fp] = os.stat(fp).st_mtime
    return mtimes


def diff_result_files(
    before: dict[str, float], after: dict[str, float],
) -> list[str]:
    """Return field files that were modified (after > before)."""
    modified = []
    for fp, old_mt in before.items():
        new_mt = after.get(fp)
        if new_mt is not None and new_mt > old_mt:
            modified.append(fp)
    return modified


def is_process_alive(pid: int | None) -> bool:
    """Check if a process with the given PID is still running."""
    if pid is None:
        return False
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True, timeout=5,
        )
        stdout = result.stdout.decode("utf-8", errors="replace")
        return str(pid) in stdout
    except Exception:
        return False


def detect_job_state(
    *,
    workspace: str,
    project_dir: str,
    pre_solve_snapshot: dict[str, float],
    process_pid: int | None,
    elapsed_s: float,
    timeout_s: float,
    floerror_baseline: str = "",
) -> tuple[str, list[str]]:
    """Determine job state from multiple signals.

    Returns (state, reasons) where state is one of:
    "succeeded", "failed", "running", "timeout", "unknown".
    """
    reasons: list[str] = []

    field_dir = os.path.join(workspace, project_dir, "DataSets", "BaseSolution")
    post_snapshot = snapshot_result_files(field_dir)

    has_baseline = len(pre_solve_snapshot) > 0
    if has_baseline:
        modified = [f for f in diff_result_files(pre_solve_snapshot, post_snapshot)
                    if f in pre_solve_snapshot]
        fields_changed = len(modified) > 0
    else:
        modified = []
        fields_changed = False
        reasons.append("No pre-solve snapshot — field change detection disabled")

    if fields_changed:
        reasons.append(f"Field files modified: {len(modified)} files changed")
    elif has_baseline:
        reasons.append("No field files modified")

    log_content, all_fatals, warns = read_floerror_log(workspace)
    if floerror_baseline:
        new_fatals = [f for f in all_fatals if f not in floerror_baseline]
    else:
        new_fatals = all_fatals
    has_fatal = len(new_fatals) > 0

    if has_fatal:
        # Surface the code + suggested action when we recognise the line.
        first = new_fatals[0]
        entries = parse_error_log(workspace)
        match = next((e for e in entries if e["raw"] == first), None)
        if match and match["suggested_action"]:
            reasons.append(
                f"New fatal: {match['code']} — {match['message'][:60]} "
                f"(action: {match['suggested_action'][:80]})"
            )
        else:
            reasons.append(f"New fatal errors: {first[:80]}")
    elif all_fatals and not has_fatal:
        reasons.append(f"Historical errors (ignored): {len(all_fatals)}")

    proc_alive = is_process_alive(process_pid)
    if proc_alive:
        reasons.append(f"Process PID {process_pid} still alive")
    elif process_pid is not None:
        reasons.append(f"Process PID {process_pid} exited")

    timed_out = elapsed_s >= timeout_s
    if timed_out:
        reasons.append(f"Timeout: {elapsed_s:.0f}s >= {timeout_s:.0f}s")

    if has_fatal:
        return "failed", reasons
    if fields_changed:
        return "succeeded", reasons
    if proc_alive and not timed_out:
        return "running", reasons
    if timed_out:
        return "timeout", reasons
    return "unknown", reasons


def collect_artifacts(
    workspace: str,
    project_dir: str,
    pre_solve_snapshot: dict[str, float],
    generated_scripts: list[str] | None = None,
) -> dict:
    """Collect result artifacts from a completed job."""
    proj_path = os.path.join(workspace, project_dir)
    field_dir = os.path.join(proj_path, "DataSets", "BaseSolution")

    post_snapshot = snapshot_result_files(field_dir)
    modified = diff_result_files(pre_solve_snapshot, post_snapshot)
    modified_rel = [os.path.relpath(f, field_dir) for f in modified]

    result_dirs = []
    if os.path.isdir(field_dir):
        result_dirs = sorted(d for d in os.listdir(field_dir)
                             if d.startswith("msp_") and os.path.isdir(os.path.join(field_dir, d)))

    log_files = []
    log_dir = os.path.join(workspace, "LogFiles")
    if os.path.isdir(log_dir):
        log_files = sorted(os.listdir(log_dir))

    error_content, _, _ = read_floerror_log(workspace)
    structured_errors = parse_error_log(workspace)

    return {
        "project_path": proj_path,
        "result_dirs": result_dirs,
        "modified_fields": modified_rel,
        "log_files": log_files,
        "generated_scripts": generated_scripts or [],
        "error_log_summary": error_content[:300] if error_content else "",
        "errors": structured_errors,
    }
