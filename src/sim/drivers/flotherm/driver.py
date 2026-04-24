"""Simcenter Flotherm driver for sim.

Provides DriverProtocol surface (detect, lint, connect, parse_output, run_file)
plus persistent session management (launch, load_project, submit_job, watch_job,
query_status, disconnect) — same pattern as the COMSOL driver.

Execution is delegated to a pluggable ExecutionBackend.  The default NullBackend
cannot execute; jobs enter WAITING_BACKEND.  A GuiAutomationBackend (using Win32
API to trigger Macro > Play FloSCRIPT) is the proven execution path.

Batch execution::

    flotherm.exe  →  GUI  →  Macro > Play FloSCRIPT  →  FloSCRIPT XML
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import time
import uuid
import zipfile
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from sim.driver import ConnectionInfo, Diagnostic, LintResult, RunResult, SolverInstall
from sim.inspect import (
    GuiDialogProbe,
    InspectCtx,
    ScreenshotProbe,
    collect_diagnostics,
    generic_probes,
)
from sim.drivers.flotherm._helpers import (
    build_solve_and_save,
    collect_artifacts,
    default_flouser,
    detect_job_state,
    find_installation,
    lint_floscript,
    lint_pack,
    pack_project_dir,
    pack_project_name,
    read_floerror_log,
    snapshot_result_files,
)

_FLOSCRIPT_MARKER = "<xml_log_file"


def _default_flotherm_probes(enable_gui: bool = True) -> list:
    """Flotherm probe list — generic_probes() + optional GUI observation.

    No driver-layer semantic assertions: "what counts as an error" is the
    agent's job, not the driver's. Probes here only extract facts.
    enable_gui=True by default because Flotherm currently only supports GUI mode.
    """
    probes: list = list(generic_probes())
    if enable_gui:
        probes.append(GuiDialogProbe(
            process_name_substrings=("flotherm", "floview", "floserv"),
            code_prefix="flotherm.gui",
        ))
        probes.append(ScreenshotProbe(
            filename_prefix="flotherm_shot",
            process_name_substrings=("flotherm", "floview", "floserv"),
        ))
    return probes


# ---------------------------------------------------------------------------
# Backend protocol
# ---------------------------------------------------------------------------


class ExecutionBackend(Protocol):
    """Interface for executing FloSCRIPT in a Flotherm session."""

    @property
    def name(self) -> str: ...

    def can_execute(self) -> bool: ...

    def dispatch(self, job: dict, session: dict) -> bool:
        """Attempt to execute the job's script.

        Must merge (not replace) into job["dispatch_metadata"].
        Return True if dispatched, False if not.
        """
        ...


class NullBackend:
    """Default backend — cannot execute. Jobs enter WAITING_BACKEND."""

    @property
    def name(self) -> str:
        return "none"

    def can_execute(self) -> bool:
        return False

    def dispatch(self, job: dict, session: dict) -> bool:
        job["dispatch_metadata"].update({
            "backend": "none",
            "reason": "No automated execution backend available",
        })
        return False


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


class FlothermDriver:
    """Sim driver for Simcenter Flotherm.

    Implements DriverProtocol (detect, lint, connect, parse_output, run_file).
    Extended API for persistent sessions: launch, load_project, submit_job,
    watch_job, query_status, query_artifacts, disconnect.
    """

    def __init__(self, backend: ExecutionBackend | None = None):
        self._install: dict | None = None
        self._session: dict | None = None
        self._project: dict | None = None
        self._backend: ExecutionBackend = backend or NullBackend()
        self._jobs: dict[str, dict] = {}
        self._process: subprocess.Popen | None = None
        self.probes = _default_flotherm_probes(enable_gui=False)

    # -- DriverProtocol surface -----------------------------------------------

    @property
    def name(self) -> str:
        return "flotherm"

    @property
    def supports_session(self) -> bool:
        return True

    def detect(self, script: Path) -> bool:
        """Return True for Flotherm files (.pack, FloSCRIPT .xml)."""
        ext = script.suffix.lower()
        if ext == ".pack":
            return True
        if ext == ".xml":
            try:
                header = script.read_bytes()[:512].decode("utf-8", errors="replace")
                return _FLOSCRIPT_MARKER in header
            except OSError:
                return False
        return False

    def lint(self, script: Path) -> LintResult:
        """Validate a .pack or FloSCRIPT .xml file. No Flotherm required.

        When sim-skills is available, FloSCRIPT files are validated against
        the XSD schema for the detected Flotherm version.
        """
        ext = script.suffix.lower()
        if ext == ".xml":
            return lint_floscript(
                script, schema_dir=self._find_schema_dir())
        if ext == ".pack":
            return lint_pack(script)
        return LintResult(ok=False, diagnostics=[Diagnostic(
            level="error",
            message=f"Unsupported file type '{script.suffix}'.")])

    def _find_schema_dir(self) -> Path | None:
        """Locate FloSCRIPT XSD schemas from sim-skills."""
        from sim.compat import find_skills_root

        skills_root = find_skills_root()
        if skills_root is None:
            return None

        # Use detected version, fall back to scanning available versions
        version = None
        info = self._install or find_installation()
        if info:
            version = info.get("version")

        if version:
            schema_dir = (
                skills_root / "flotherm" / "reference" / "flotherm"
                / version / "examples" / "floscript" / "schema"
            )
            if schema_dir.is_dir():
                return schema_dir
            # Also try base/reference path variant
            schema_dir = (
                skills_root / "flotherm" / "base" / "reference" / "flotherm"
                / version / "examples" / "floscript" / "schema"
            )
            if schema_dir.is_dir():
                return schema_dir

        # Fallback: find any available schema directory
        for pattern in (
            "flotherm/reference/flotherm/*/examples/floscript/schema",
            "flotherm/base/reference/flotherm/*/examples/floscript/schema",
        ):
            matches = sorted(skills_root.glob(pattern), reverse=True)
            if matches:
                return matches[0]

        return None

    def connect(self) -> ConnectionInfo:
        """Check Flotherm installation. Does not launch anything."""
        info = find_installation()
        if info is None:
            return ConnectionInfo(
                solver="flotherm", version=None, status="not_installed",
                message="Simcenter Flotherm not found.")
        return ConnectionInfo(
            solver="flotherm", version=info["version"], status="ok",
            message=f"Simcenter Flotherm {info['version']} found at {info['bat_path']}",
            solver_version=info["version"])

    def parse_output(self, stdout: str) -> dict:
        """Extract last JSON line from stdout."""
        for line in reversed(stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        return {}

    def detect_installed(self) -> list[SolverInstall]:
        """Enumerate Simcenter Flotherm installations on this host.

        Thin wrapper around the existing _helpers.find_installation()
        which already walks FLOTHERM_ROOT → PATH → glob of common
        install dirs (Siemens 2504/2412/2406/...). Returns at most one
        install — Flotherm has a single canonical bat_path per host.
        """
        info = find_installation()
        if info is None:
            return []
        return [
            SolverInstall(
                name="flotherm",
                version=info.get("version", "?"),
                path=info.get("install_root", ""),
                source="find_installation",
                extra={
                    "bat_path": info.get("bat_path", ""),
                    "floserv_path": info.get("floserv_path", ""),
                    "raw_version": info.get("version", "?"),
                },
            )
        ]

    def run_file(self, script: Path, **kwargs) -> RunResult:
        """Execute a Flotherm project or script via the session lifecycle.

        Creates an ephemeral session: launch → load/submit → watch → disconnect.
        """
        info = find_installation()
        if info is None:
            raise RuntimeError("Simcenter Flotherm not found.")

        ext = script.suffix.lower()
        if ext == ".pack":
            return self._run_pack(script, **kwargs)
        if ext == ".xml":
            return self._run_xml(script, **kwargs)
        raise RuntimeError(f"Unsupported file type '{script.suffix}'.")

    # -- Session lifecycle (like COMSOL's launch/run/disconnect) ---------------

    def launch(
        self, *, workspace: str | None = None, ui_mode: str = "gui", **kwargs,
    ) -> dict:
        """Start a Flotherm session.

        Locates installation, sets up workspace, optionally launches GUI.
        Returns session info dict.
        """
        if self._session and self._session.get("state") == "ready":
            raise RuntimeError("Session already active. Call disconnect() first.")

        self._install = find_installation()
        if self._install is None:
            self._session = {"state": "launch_failed", "session_id": str(uuid.uuid4())}
            raise RuntimeError("Simcenter Flotherm not found.")

        ws = workspace or default_flouser(self._install["install_root"])
        os.makedirs(ws, exist_ok=True)

        pid = None
        if ui_mode == "gui":
            pid = self._launch_gui(ws)

        self._session = {
            "session_id": str(uuid.uuid4()),
            "state": "ready",
            "ui_mode": ui_mode,
            "backend": self._backend.name,
            "workspace": ws,
            "install_root": self._install["install_root"],
            "bat_path": self._install["bat_path"],
            "version": self._install["version"],
            "launched_at": datetime.now(timezone.utc).isoformat(),
            "process_pid": pid,
            "run_count": 0,
            "active_project": None,
        }
        self.probes = _default_flotherm_probes(enable_gui=(ui_mode == "gui"))
        if ui_mode == "gui":
            from sim.gui import GuiController
            self._gui = GuiController(
                process_name_substrings=("flotherm", "floview", "floserv"),
            )
        return self._session

    def run(self, code: str, label: str = "") -> dict:
        """Execute a Flotherm command in the active session, with probe observation.

        Wraps _dispatch() with timing, workdir snapshot, and collect_diagnostics()
        so every run() result carries structured diagnostics and artifact lists —
        same contract as Fluent and COMSOL drivers.
        """
        import time as _t
        from pathlib import Path as _Path

        workdir = (self._session or {}).get("workspace", "")
        before: list[str] = []
        if workdir:
            try:
                wd = _Path(workdir)
                before = sorted(
                    str(p.relative_to(wd)).replace("\\", "/")
                    for p in wd.rglob("*") if p.is_file()
                )
            except Exception:
                pass

        t0 = _t.monotonic()
        result = self._dispatch(code, label)
        wall = _t.monotonic() - t0

        ctx = InspectCtx(
            stdout="",
            stderr="",
            workdir=workdir,
            wall_time_s=wall,
            exit_code=0 if result.get("ok") else 1,
            driver_name=self.name,
            session_ns={},
            workdir_before=before,
        )
        diags, arts = collect_diagnostics(self.probes, ctx)
        result["diagnostics"] = [d.to_dict() for d in diags]
        result["artifacts"] = [a.to_dict() for a in arts]
        return result

    def _dispatch(self, code: str, label: str = "") -> dict:
        """Execute a Flotherm command in the active session.

        Supported commands:
          - A path to a .pack file → load_project() + play FloSCRIPT to open in GUI
          - A path to a .xml FloSCRIPT → play it via GUI automation
          - "solve" → generate solve FloSCRIPT and play via GUI
          - "status" → query_status()
        """
        text = code.strip()

        # #!python → execute raw Python in server process (dev mode only)
        # WARNING: This is exec() — arbitrary code execution. Only available
        # when SIM_DEV_MODE=1 is set in the server environment.
        if text.startswith("#!python"):
            if not os.environ.get("SIM_DEV_MODE"):
                return {"ok": False, "error": "#!python requires SIM_DEV_MODE=1 (security: arbitrary code execution)"}
            return self._exec_python(text[len("#!python"):].strip())

        # .pack file → import project into GUI via FloSCRIPT project_import
        if text.lower().endswith(".pack") and os.path.isfile(text):
            result = self.load_project(Path(text))
            # Clean up extracted dir so project_import can re-extract
            import shutil
            proj_path = os.path.join(result["workspace"], result["project_dir"])
            if os.path.isdir(proj_path):
                shutil.rmtree(proj_path)
            # Generate import FloSCRIPT
            import_script = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<xml_log_file version="1.0">\n'
                f'    <project_import filename="{text}" import_type="Pack File"/>\n'
                '</xml_log_file>'
            )
            script_path = self._write_script(import_script, "import_project")
            gui_result = self._play_floscript(script_path)
            return {"ok": True, "action": "import_project", **result, "gui": gui_result}

        # .xml FloSCRIPT → play via GUI automation
        if text.lower().endswith(".xml") and os.path.isfile(text):
            gui_result = self._play_floscript(text)
            return {
                "ok": gui_result.get("ok", False),
                "action": "play_floscript",
                "script": text,
                "gui": gui_result,
            }

        # "solve" → play solve FloSCRIPT via GUI
        if text.lower() == "solve":
            if self._project is None:
                return {"ok": False, "error": "No project loaded. Load a .pack first."}
            # Project is already loaded in GUI after import — just start solver
            script_content = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<xml_log_file version="1.0">\n'
                '    <start start_type="solver"/>\n'
                '</xml_log_file>'
            )
            script_path = self._write_script(script_content, label or "solve")
            gui_result = self._play_floscript(script_path)
            return {"ok": True, "action": "solve", "script": script_path, "gui": gui_result}

        # "status" → query status
        if text.lower() == "status":
            result = self.query_status()
            return {"ok": True, "action": "query_status", **result}

        return {
            "ok": False,
            "error": f"Unknown command: {text!r}. "
                     "Use a .pack path, .xml path, 'solve', 'status', or '#!python ...'.",
        }

    def _exec_python(self, code: str) -> dict:
        """Execute raw Python in the server process (dev mode).

        WARNING: This runs arbitrary code via exec(). Only available when
        SIM_DEV_MODE=1 is set. Never enable in production.
        """
        import io
        import logging
        import traceback
        logging.warning("Flotherm #!python exec — dev mode, arbitrary code execution")
        from contextlib import redirect_stdout, redirect_stderr

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        namespace = {"driver": self, "_result": None}

        try:
            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                exec(code, namespace)  # noqa: S102
            return {
                "ok": True,
                "action": "python",
                "stdout": stdout_buf.getvalue(),
                "stderr": stderr_buf.getvalue(),
                "result": namespace.get("_result"),
            }
        except Exception:
            return {
                "ok": False,
                "action": "python",
                "stdout": stdout_buf.getvalue(),
                "stderr": stderr_buf.getvalue(),
                "error": traceback.format_exc(),
            }

    def _play_floscript(self, script_path: str) -> dict:
        """Trigger Macro > Play FloSCRIPT via Win32 GUI automation."""
        try:
            from sim.drivers.flotherm._win32_backend import play_floscript
            return play_floscript(script_path)
        except ImportError:
            return {"ok": False, "error": "Win32 backend not available (not on Windows)"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def load_project(self, pack_or_dir: Path) -> dict:
        """Load a project into the session."""
        self._require_session()
        ws = self._session["workspace"]

        if pack_or_dir.suffix.lower() == ".pack":
            proj_dir = pack_project_dir(pack_or_dir)
            if proj_dir is None:
                raise RuntimeError(f"Cannot identify project in {pack_or_dir}")
            proj_path = os.path.join(ws, proj_dir)
            if not os.path.isdir(proj_path):
                with zipfile.ZipFile(pack_or_dir) as z:
                    z.extractall(ws)
            source, pack_path = "pack", str(pack_or_dir)
        elif pack_or_dir.is_dir():
            proj_dir = pack_or_dir.name
            source, pack_path = "existing", None
        else:
            raise RuntimeError(f"Cannot load '{pack_or_dir}'.")

        proj_path = os.path.join(ws, proj_dir)
        base_sol = os.path.join(proj_path, "DataSets", "BaseSolution")
        scenarios = []
        if os.path.isdir(base_sol):
            scenarios = sorted(d for d in os.listdir(base_sol)
                               if d.startswith("msp_") and os.path.isdir(os.path.join(base_sol, d)))

        self._project = {
            "project_dir": proj_dir,
            "project_name": pack_project_name(proj_dir),
            "workspace": ws,
            "source": source,
            "pack_path": pack_path,
            "scenario_dirs": scenarios,
        }
        self._session["active_project"] = proj_dir
        return self._project

    def submit_job(self, *, label: str = "solve", script: str | Path | None = None) -> dict:
        """Submit a solve job for the active project."""
        self._require_session()
        session = self._session

        # Generate FloSCRIPT if not provided
        if script is not None:
            if isinstance(script, Path) or os.path.isfile(str(script)):
                script_path = str(script)
                script_content = Path(script_path).read_text(encoding="utf-8", errors="replace")
            else:
                script_content = script
                script_path = self._write_script(script_content, label)
        else:
            if self._project is None:
                raise RuntimeError("No project loaded.")
            script_content = build_solve_and_save(self._project["project_name"])
            script_path = self._write_script(script_content, label)

        now = datetime.now(timezone.utc).isoformat()
        job = {
            "job_id": str(uuid.uuid4()),
            "session_id": session["session_id"],
            "label": label,
            "state": "pending",
            "script_path": script_path,
            "script_content": script_content,
            "project_dir": self._project["project_dir"] if self._project else None,
            "submitted_at": now,
            "started_at": None,
            "finished_at": None,
            "elapsed_s": None,
            "backend": self._backend.name,
            "dispatch_metadata": {},
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "artifacts": None,
            "errors": [],
            "state_reasons": [],
        }

        # Pre-solve baselines
        if self._project:
            field_dir = os.path.join(
                session["workspace"], self._project["project_dir"],
                "DataSets", "BaseSolution")
            job["dispatch_metadata"]["pre_solve_snapshot"] = snapshot_result_files(field_dir)
            baseline, _, _ = read_floerror_log(session["workspace"])
            job["dispatch_metadata"]["floerror_baseline"] = baseline

        # Dispatch to backend
        dispatched = self._backend.dispatch(job, session)
        if dispatched:
            job["state"] = "dispatched"
            job["started_at"] = now
        else:
            job["state"] = "waiting_backend"

        self._jobs[job["job_id"]] = job
        session["run_count"] += 1
        return job

    def watch_job(
        self, job_id: str, *, timeout: float = 300,
        poll_interval: float = 2.0, watch_anyway: bool = False,
    ) -> dict:
        """Poll job state until terminal or timeout."""
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(f"No job with id {job_id}")
        if job["state"] == "waiting_backend" and not watch_anyway:
            return job

        self._require_session()
        session = self._session
        pre_snapshot = job["dispatch_metadata"].get("pre_solve_snapshot", {})
        floerror_baseline = job["dispatch_metadata"].get("floerror_baseline", "")

        start = time.monotonic()
        while (time.monotonic() - start) < timeout:
            elapsed = time.monotonic() - start

            state, reasons = detect_job_state(
                workspace=session["workspace"],
                project_dir=job["project_dir"] or "",
                pre_solve_snapshot=pre_snapshot,
                process_pid=session["process_pid"],
                elapsed_s=elapsed,
                timeout_s=timeout,
                floerror_baseline=floerror_baseline,
            )

            job["state"] = state
            job["state_reasons"] = reasons
            job["elapsed_s"] = round(elapsed, 3)

            if state in ("succeeded", "failed", "timeout"):
                job["finished_at"] = datetime.now(timezone.utc).isoformat()
                break

            time.sleep(poll_interval)
        else:
            job["state"] = "timeout"
            job["state_reasons"].append(f"watch_job exhausted after {timeout}s")
            job["finished_at"] = datetime.now(timezone.utc).isoformat()
            job["elapsed_s"] = round(time.monotonic() - start, 3)

        # Collect artifacts
        if job["project_dir"]:
            job["artifacts"] = collect_artifacts(
                workspace=session["workspace"],
                project_dir=job["project_dir"],
                pre_solve_snapshot=pre_snapshot,
                generated_scripts=[job["script_path"]] if job["script_path"] else None,
            )
            if job["artifacts"].get("error_log_summary"):
                for line in job["artifacts"]["error_log_summary"].splitlines():
                    if "ERROR" in line:
                        job["errors"].append(line.strip())

        return job

    def query_status(self) -> dict:
        """Snapshot of current session state."""
        from sim.drivers.flotherm._helpers import is_process_alive
        last_job = list(self._jobs.values())[-1] if self._jobs else None
        proc_alive = False
        if self._session and self._session.get("process_pid"):
            proc_alive = is_process_alive(self._session["process_pid"])
        return {
            "session": self._session,
            "active_project": self._project,
            "last_job": last_job,
            "total_jobs": len(self._jobs),
            "process_alive": proc_alive,
        }

    def query_artifacts(self, job_id: str | None = None) -> dict:
        """Collect artifacts for a job."""
        if job_id:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(f"No job with id {job_id}")
        else:
            if not self._jobs:
                raise RuntimeError("No jobs submitted yet.")
            job = list(self._jobs.values())[-1]

        if job.get("artifacts"):
            return job["artifacts"]

        self._require_session()
        pre_snapshot = job["dispatch_metadata"].get("pre_solve_snapshot", {})
        artifacts = collect_artifacts(
            workspace=self._session["workspace"],
            project_dir=job["project_dir"] or "",
            pre_solve_snapshot=pre_snapshot,
            generated_scripts=[job["script_path"]] if job["script_path"] else None,
        )
        job["artifacts"] = artifacts
        return artifacts

    _PROCESS_NAMES = ("floserv", "floview", "flotherm")

    def disconnect(self, *, kill_process: bool = True, keep_workspace: bool = True) -> dict:
        """End the session."""
        if kill_process:
            self._kill_flotherm_processes()
            self._process = None
        if self._session:
            self._session["state"] = "disconnected"
        self._project = None
        return {"ok": True, "disconnected": True}

    # -- Internal helpers -----------------------------------------------------

    def _kill_flotherm_processes(self) -> None:
        """Kill all Flotherm-related processes (floserv, floview, flotherm)."""
        if os.name == "nt":
            for name in self._PROCESS_NAMES:
                with suppress(Exception):
                    subprocess.run(
                        ["taskkill", "/F", "/IM", f"{name}.exe"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
        else:
            # Fallback: kill by stored PID + parent Popen
            if self._session and self._session.get("process_pid"):
                with suppress(Exception):
                    os.kill(self._session["process_pid"], signal.SIGTERM)
            if self._process is not None:
                with suppress(Exception):
                    self._process.kill()

    def _launch_gui(self, workspace: str) -> int | None:
        """Launch Flotherm GUI via flotherm.exe."""
        if self._install is None:
            return None

        exe_path = os.path.join(
            os.path.dirname(self._install["bat_path"]), "flotherm.exe")
        if not os.path.isfile(exe_path):
            exe_path = self._install["bat_path"]

        bin_dir = os.path.dirname(self._install["bat_path"])

        try:
            self._ensure_license_env()
            self._process = subprocess.Popen(
                [exe_path], cwd=bin_dir,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
            return self._wait_for_floserv(timeout=30)
        except Exception:
            return None

    @staticmethod
    def _ensure_license_env() -> None:
        """Ensure SALT_LICENSE_SERVER is set from the Windows registry if missing."""
        if os.environ.get("SALT_LICENSE_SERVER"):
            return
        if os.name == "nt":
            import winreg
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    if hive == winreg.HKEY_CURRENT_USER:
                        key = winreg.OpenKey(hive, r"Environment")
                    else:
                        key = winreg.OpenKey(
                            hive,
                            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")
                    val, _ = winreg.QueryValueEx(key, "SALT_LICENSE_SERVER")
                    winreg.CloseKey(key)
                    if val:
                        os.environ["SALT_LICENSE_SERVER"] = val
                        return
                except OSError:
                    pass

    @staticmethod
    def _find_floserv_pid() -> int | None:
        """Find a running floserv.exe PID via tasklist."""
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq floserv.exe", "/NH"],
                capture_output=True, timeout=5)
            stdout = result.stdout.decode("utf-8", errors="replace")
            for line in stdout.splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[0].lower() == "floserv.exe":
                    try:
                        return int(parts[1])
                    except ValueError:
                        continue
        except Exception:
            pass
        return None

    def _wait_for_floserv(self, timeout: float = 30) -> int | None:
        """Poll until floserv.exe appears."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            pid = self._find_floserv_pid()
            if pid is not None:
                return pid
            time.sleep(1)
        return None

    def _write_script(self, xml_content: str, label: str) -> str:
        """Write FloSCRIPT XML to workspace."""
        self._require_session()
        ws = self._session["workspace"]
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)
        path = os.path.join(ws, f"_sim_{safe}.xml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(xml_content)
        return path

    def _require_session(self) -> None:
        if self._session is None or self._session.get("state") != "ready":
            raise RuntimeError("No active session. Call launch() first.")

    # -- run_file internals ---------------------------------------------------

    def _run_pack(self, pack: Path, **kwargs) -> RunResult:
        """One-shot: launch → load → submit → watch → disconnect."""
        try:
            self.launch(ui_mode=kwargs.get("ui_mode", "gui"),
                        workspace=kwargs.get("workspace"))
            self.load_project(pack)
            job = self.submit_job(label="solve-all")
            if job["state"] == "waiting_backend":
                return self._job_to_result(job, pack)
            job = self.watch_job(job["job_id"], timeout=kwargs.get("timeout", 300))
            return self._job_to_result(job, pack)
        finally:
            self.disconnect(keep_workspace=True)

    def _run_xml(self, script: Path, **kwargs) -> RunResult:
        """One-shot: launch → exec script → watch → disconnect."""
        try:
            self.launch(ui_mode=kwargs.get("ui_mode", "gui"),
                        workspace=kwargs.get("workspace"))
            job = self.submit_job(label=script.stem, script=script)
            if job["state"] == "waiting_backend":
                return self._job_to_result(job, script)
            job = self.watch_job(job["job_id"], timeout=kwargs.get("timeout", 300))
            return self._job_to_result(job, script)
        finally:
            self.disconnect(keep_workspace=True)

    @staticmethod
    def _job_to_result(job: dict, script: Path) -> RunResult:
        state_to_exit = {
            "succeeded": 0, "pending": 2, "waiting_backend": 3,
            "dispatched": 2, "running": 2, "failed": 1,
            "timeout": 4, "unknown": 5,
        }
        stdout_parts = [f"state: {job['state']}", f"job_id: {job['job_id']}"]
        if job["state_reasons"]:
            stdout_parts.append("reasons:")
            for r in job["state_reasons"]:
                stdout_parts.append(f"  - {r}")
        stderr_parts = list(job["errors"])
        if job["dispatch_metadata"].get("reason"):
            stderr_parts.insert(0, job["dispatch_metadata"]["reason"])

        return RunResult(
            exit_code=state_to_exit.get(job["state"], 5),
            stdout="\n".join(stdout_parts),
            stderr="\n".join(stderr_parts),
            duration_s=job["elapsed_s"] or 0.0,
            script=str(script),
            solver="flotherm",
            timestamp=job["submitted_at"] or datetime.now(timezone.utc).isoformat(),
        )
