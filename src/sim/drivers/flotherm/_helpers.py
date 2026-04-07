"""Internal helpers for the Flotherm driver.

Installation detection, linting, FloSCRIPT generation, and status monitoring.
This module is not part of the public API — use FlothermDriver instead.
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import time
import zipfile
from contextlib import suppress
from pathlib import Path
from xml.dom import minidom
from xml.etree import ElementTree
from xml.etree.ElementTree import Element, SubElement, tostring

from sim.driver import Diagnostic, LintResult

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
    # 1. FLOTHERM_ROOT env var
    env_root = os.environ.get("FLOTHERM_ROOT", "").strip()
    if env_root:
        bat = os.path.join(env_root, "WinXP", "bin", "flotherm.bat")
        serv = os.path.join(env_root, "WinXP", "bin", "floserv.exe")
        if os.path.isfile(bat):
            version = extract_version(env_root) or "unknown"
            return {"bat_path": bat, "floserv_path": serv,
                    "install_root": env_root, "version": version}

    # 2. PATH
    bat_on_path = shutil.which("flotherm")
    if bat_on_path:
        root = str(Path(bat_on_path).parent.parent.parent)
        serv = str(Path(bat_on_path).parent / "floserv.exe")
        version = extract_version(bat_on_path) or "unknown"
        return {"bat_path": bat_on_path, "floserv_path": serv,
                "install_root": root, "version": version}

    # 3. Glob common install dirs
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


def pack_project_dir(pack: Path) -> str | None:
    """Return the top-level project directory name from inside a .pack ZIP."""
    try:
        with zipfile.ZipFile(pack) as z:
            names = z.namelist()
        dirs = {e.split("/")[0] for e in names if e.split("/")[0]}
        if dirs:
            return sorted(dirs)[0]
    except Exception:
        pass
    return None


def pack_project_name(proj_dir: str) -> str:
    """Extract short project name from directory (before the GUID dot)."""
    return proj_dir.split(".")[0] if "." in proj_dir else proj_dir


def default_flouser(install_root: str) -> str:
    """Return the default FLOUSERDIR for an installation."""
    env = os.environ.get("FLOUSERDIR", "").strip()
    if env:
        return env
    return os.path.join(install_root, "flouser")


# ---------------------------------------------------------------------------
# Linting
# ---------------------------------------------------------------------------

_FLOSCRIPT_ROOT = "xml_log_file"
_SOLVE_COMMANDS = ("solve_all", "solve_scenario", "start")


def lint_pack(pack: Path) -> LintResult:
    """Validate a .pack project archive."""
    diagnostics: list[Diagnostic] = []
    try:
        data = pack.read_bytes()
    except OSError as e:
        return LintResult(ok=False, diagnostics=[
            Diagnostic(level="error", message=f"Cannot read file: {e}")])
    if not data:
        return LintResult(ok=False, diagnostics=[
            Diagnostic(level="error", message="Pack file is empty")])
    try:
        with zipfile.ZipFile(pack) as z:
            names = z.namelist()
    except zipfile.BadZipFile as e:
        return LintResult(ok=False, diagnostics=[
            Diagnostic(level="error", message=f"Invalid ZIP/pack file: {e}")])
    top_level_dirs = {n.split("/")[0] for n in names if "/" in n}
    if not top_level_dirs:
        diagnostics.append(Diagnostic(
            level="warning", message="Pack file contains no project directory."))
    return LintResult(ok=True, diagnostics=diagnostics)


def lint_floscript(script: Path) -> LintResult:
    """Validate a FloSCRIPT XML file."""
    diagnostics: list[Diagnostic] = []
    try:
        text = script.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return LintResult(ok=False, diagnostics=[
            Diagnostic(level="error", message=f"Cannot read file: {e}")])
    if not text.strip():
        return LintResult(ok=False, diagnostics=[
            Diagnostic(level="error", message="Script is empty")])
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as e:
        return LintResult(ok=False, diagnostics=[
            Diagnostic(level="error", message=f"XML parse error: {e}")])
    if root.tag != _FLOSCRIPT_ROOT:
        diagnostics.append(Diagnostic(
            level="error",
            message=f"Expected root <xml_log_file>, got <{root.tag}>."))
        return LintResult(ok=False, diagnostics=diagnostics)
    # Check for solve commands (direct or inside external_command)
    has_solve = False
    for child in root:
        if child.tag in _SOLVE_COMMANDS:
            has_solve = True
            break
        if child.tag == "external_command":
            for gc in child:
                if gc.tag in _SOLVE_COMMANDS:
                    has_solve = True
                    break
    if not has_solve:
        diagnostics.append(Diagnostic(
            level="warning",
            message="No solve/start command found \u2014 "
                    "script may configure but not run a simulation."))
    return LintResult(ok=True, diagnostics=diagnostics)


# ---------------------------------------------------------------------------
# FloSCRIPT generation
# ---------------------------------------------------------------------------


def _pretty_xml(root: Element) -> str:
    raw = tostring(root, encoding="unicode")
    dom = minidom.parseString(raw)
    return dom.toprettyxml(indent="    ", encoding=None)


def build_solve_and_save(project_name: str) -> str:
    """Build FloSCRIPT: unlock → load → solve → save (Drawing Board syntax)."""
    root = Element("xml_log_file", version="1.0")
    SubElement(root, "project_unlock", project_name=project_name)
    SubElement(root, "project_load", project_name=project_name)
    SubElement(root, "start", start_type="solver")
    return _pretty_xml(root)


def build_solve_scenario(project_name: str, scenario_id: str) -> str:
    """Build FloSCRIPT to solve a specific scenario."""
    root = Element("xml_log_file", version="1.0")
    SubElement(root, "project_unlock", project_name=project_name)
    SubElement(root, "project_load", project_name=project_name)
    ext = SubElement(root, "external_command", process="CommandCentre")
    solve = SubElement(ext, "solve_scenario")
    SubElement(solve, "scenario_id", scenario_id=scenario_id)
    return _pretty_xml(root)


def build_custom(commands: list[dict]) -> str:
    """Build FloSCRIPT from a list of command specs."""
    root = Element("xml_log_file", version="1.0")
    for cmd in commands:
        _add_command(root, cmd)
    return _pretty_xml(root)


def _add_command(parent: Element, spec: dict) -> None:
    process = spec.get("process")
    if process:
        wrapper = SubElement(parent, "external_command", process=process)
        inner_spec = {k: v for k, v in spec.items() if k != "process"}
        _add_command(wrapper, inner_spec)
        return
    attrs = spec.get("attrs", {})
    elem = SubElement(parent, spec["command"], **attrs)
    for child in spec.get("children", []):
        _add_command(elem, child)


# ---------------------------------------------------------------------------
# Status detection
# ---------------------------------------------------------------------------

FIELD_NAMES = (
    "Temperature", "Pressure", "Speed",
    "XVelocity", "YVelocity", "ZVelocity", "TurbVis",
)

_FATAL_PATTERNS = ("E/11029", "E/9012")
_WARNING_PATTERNS = ("registerStart runTable exception",)


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


def read_floerror_log(workspace: str) -> tuple[str, list[str], list[str]]:
    """Read floerror.log; return (full_content, fatal_errors, warnings)."""
    logpath = os.path.join(workspace, "floerror.log")
    if not os.path.isfile(logpath):
        return "", [], []
    with suppress(OSError):
        content = open(logpath, encoding="utf-8", errors="replace").read()
        fatals = [l.strip() for l in content.splitlines()
                  if any(p in l for p in _FATAL_PATTERNS)]
        warns = [l.strip() for l in content.splitlines()
                 if any(p in l for p in _WARNING_PATTERNS)]
        return content, fatals, warns
    return "", [], []


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

    # Signal 1: Field file changes
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

    # Signal 2: floerror.log (only NEW errors since baseline)
    log_content, all_fatals, warns = read_floerror_log(workspace)
    if floerror_baseline:
        new_fatals = [f for f in all_fatals if f not in floerror_baseline]
    else:
        new_fatals = all_fatals
    has_fatal = len(new_fatals) > 0

    if has_fatal:
        reasons.append(f"New fatal errors: {new_fatals[0][:80]}")
    elif all_fatals and not has_fatal:
        reasons.append(f"Historical errors (ignored): {len(all_fatals)}")

    # Signal 3: Process alive
    proc_alive = is_process_alive(process_pid)
    if proc_alive:
        reasons.append(f"Process PID {process_pid} still alive")
    elif process_pid is not None:
        reasons.append(f"Process PID {process_pid} exited")

    # Signal 4: Timeout
    timed_out = elapsed_s >= timeout_s
    if timed_out:
        reasons.append(f"Timeout: {elapsed_s:.0f}s >= {timeout_s:.0f}s")

    # Decision logic (priority: fatal > fields > process > timeout)
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

    return {
        "project_path": proj_path,
        "result_dirs": result_dirs,
        "modified_fields": modified_rel,
        "log_files": log_files,
        "generated_scripts": generated_scripts or [],
        "error_log_summary": error_content[:300] if error_content else "",
    }
