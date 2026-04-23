"""IAP-based persistent session runtime for ANSA.

Uses the official Inter-ANSA Protocol (IAP) to maintain a long-lived
ANSA process and execute Python snippets inside it without cold-starting
each time.

Protocol flow:
    launch()        →  start ansa_win64.exe -nolauncher -listenport <port> -foregr -nogui
    connect()       →  IAPConnection(port) + hello()
    exec_snippet()  →  run_script_text(code, "main", keep_database)
    exec_file()     →  run_script_file(path, "main", keep_database)
    disconnect()    →  goodbye(shut_down) + cleanup
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import uuid
from pathlib import Path

from sim.drivers.ansa.schemas import RunRecord, SessionInfo

# ---------------------------------------------------------------------------
# Import the official AnsaProcessModule (IAP protocol implementation).
# It lives in the ANSA install: scripts/RemoteControl/ansa/AnsaProcessModule.py
# We add it to sys.path dynamically so no copy is needed.
# ---------------------------------------------------------------------------
_IAP_MODULE = None


def _get_iap_module():
    """Lazily import AnsaProcessModule from the ANSA installation."""
    global _IAP_MODULE
    if _IAP_MODULE is not None:
        return _IAP_MODULE

    import sys
    from sim.drivers.ansa.driver import _find_installation

    install = _find_installation()
    if install is None:
        raise RuntimeError("ANSA not found — cannot import AnsaProcessModule")

    bat_path = install[0]
    ansa_dir = str(Path(bat_path).parent)
    iap_path = os.path.join(ansa_dir, "scripts", "RemoteControl", "ansa")

    if not os.path.isdir(iap_path):
        raise RuntimeError(f"IAP module not found at {iap_path}")

    if iap_path not in sys.path:
        sys.path.insert(0, iap_path)

    import AnsaProcessModule as mod
    _IAP_MODULE = mod
    return mod


def _find_free_port() -> int:
    """Find a free TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _wait_for_port(port: int, timeout: float = 30.0) -> bool:
    """Wait until a TCP port is accepting connections."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("localhost", port), timeout=1):
                return True
        except (ConnectionRefusedError, OSError):
            time.sleep(0.5)
    return False


class AnsaRuntime:
    """Manages a persistent ANSA session via IAP (Inter-ANSA Protocol)."""

    def __init__(self, sim_dir: Path | None = None):
        self._sim_dir = sim_dir or (Path.cwd() / ".sim")
        self._session: SessionInfo | None = None
        self._connection = None  # IAPConnection instance
        self._process: subprocess.Popen | None = None
        self._last_record: RunRecord | None = None

    # ── lifecycle ────────────────────────────────────────────────────────────

    def launch(self, port: int | None = None, ui_mode: str = "gui") -> SessionInfo:
        """Start ANSA in listener mode and establish IAP connection.

        Args:
            port: TCP port for IAP. Auto-assigned if None.
            ui_mode: "no_gui" (headless) or "gui" (visible ANSA window).
                     With "gui", every exec_snippet() call is visible in
                     the ANSA GUI in real time — like pyfluent ui_mode="gui".

        Returns a SessionInfo describing the live session.
        """
        if self._session is not None:
            raise RuntimeError(
                f"Session already active (id={self._session.session_id}). "
                "Call disconnect() first."
            )

        iap = _get_iap_module()

        # Resolve ANSA executable
        from sim.drivers.ansa.driver import _find_installation, _extract_version
        install = _find_installation()
        if install is None:
            raise RuntimeError("ANSA not found")
        bat_path = install[0]
        bat_dir = str(Path(bat_path).parent)
        parent_dir = str(Path(bat_dir).parent)
        version = _extract_version(bat_dir) or "25.0.0"
        shared_dir = os.path.join(parent_dir, f"shared_v{version}")
        exe_path = os.path.join(shared_dir, "win64", "ansa_win64.exe")

        if not os.path.isfile(exe_path):
            raise RuntimeError(f"ansa_win64.exe not found at {exe_path}")

        # Pick port
        if port is None:
            port = _find_free_port()

        # Build environment
        env = os.environ.copy()
        env.setdefault("ANSA_SRV", "localhost")
        env["ANSA_EXEC_DIR"] = bat_dir + os.sep
        env["ANSA_EXEC_PATH"] = bat_dir + os.sep
        env["BETA_SHARED_DIR"] = shared_dir + os.sep
        env["QTDIR"] = os.path.join(shared_dir, "win64")
        env["QT_PLUGIN_PATH"] = os.path.join(shared_dir, "win64", "plugins")
        env["QTWEBENGINE_DISABLE_SANDBOX"] = "1"
        env["PYTHONHOME"] = os.path.join(shared_dir, "python", "win64") + os.sep
        env["ANSA_HOME"] = os.path.join(bat_dir, "config") + os.sep
        env["HDF5_DISABLE_VERSION_CHECK"] = "2"

        # Launch ANSA in listener mode
        # NOTE: stdout/stderr must NOT be PIPE — ANSA blocks/crashes if
        # its output pipe fills up. Use DEVNULL for headless operation.
        cmd = [exe_path, "-nolauncher", "-listenport", str(port), "-foregr"]
        if ui_mode != "gui":
            cmd.append("-nogui")
        self._process = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Wait for port to accept connections
        if not _wait_for_port(port, timeout=30.0):
            self._kill_process()
            raise RuntimeError(
                f"ANSA did not start listening on port {port} within 30s"
            )

        # Connect via IAP (has its own retry loop, up to 60s)
        self._connection = iap.IAPConnection(port)
        resp = self._connection.hello()
        if not resp.success():
            self._kill_process()
            raise RuntimeError(
                f"IAP hello() failed with ResultCode {resp.get_result_code()}"
            )

        session_id = str(uuid.uuid4())
        self._session = SessionInfo(
            session_id=session_id,
            mode="batch",
            source="launch",
            port=port,
            pid=self._process.pid if self._process else None,
        )
        return self._session

    def connect(self, port: int) -> SessionInfo:
        """Connect to an already-running ANSA in listener mode.

        Use this when ANSA was started externally with -listenport.
        """
        if self._session is not None:
            raise RuntimeError("Session already active. Call disconnect() first.")

        iap = _get_iap_module()

        self._connection = iap.IAPConnection(port)
        resp = self._connection.hello()
        if not resp.success():
            raise RuntimeError(
                f"IAP hello() failed with ResultCode {resp.get_result_code()}"
            )

        session_id = str(uuid.uuid4())
        self._session = SessionInfo(
            session_id=session_id,
            mode="batch",
            source="connection",
            port=port,
        )
        return self._session

    def disconnect(self, keep_listening: bool = False) -> None:
        """Terminate the IAP connection and optionally shut down ANSA."""
        iap = _get_iap_module()

        if self._connection is not None:
            try:
                action = (
                    iap.PostConnectionAction.keep_listening
                    if keep_listening
                    else iap.PostConnectionAction.shut_down
                )
                self._connection.goodbye(action)
            except Exception:
                pass
            try:
                self._connection.close()
            except Exception:
                pass
            self._connection = None

        if not keep_listening:
            self._kill_process()

        self._session = None

    # ── snippet execution ────────────────────────────────────────────────────

    def exec_snippet(self, code: str, label: str = "ansa-snippet") -> RunRecord:
        """Execute a Python code snippet inside the active ANSA session.

        The code is sent to ANSA via IAP run_script_text(). If the code
        defines a main() function, it will be called and its return value
        (must be a string dict) is captured.
        """
        if self._session is None or self._connection is None:
            raise RuntimeError("No active session. Call launch() or connect() first.")

        iap = _get_iap_module()

        # Wrap code so it always has a main() that returns a dict
        has_main = "def main(" in code
        if not has_main:
            # Wrap bare code in a main() that execs it
            wrapped = (
                "def main():\n"
                "    import json\n"
                "    _ns = {}\n"
                f"    exec({code!r}, _ns)\n"
                "    return _ns.get('_result', {'executed': 'true'})\n"
            )
            exec_code = wrapped
            entry = "main"
        else:
            exec_code = code
            entry = "main"

        started_at = time.time()
        stdout = ""
        error = None
        result = None
        ok = True

        try:
            resp = self._connection.run_script_text(
                exec_code,
                entry,
                iap.PreExecutionDatabaseAction.keep_database,
            )
            if resp.success():
                ret_type = resp.get_script_return_type()
                if ret_type == iap.ScriptReturnType.string_dict:
                    result = resp.get_response_dict()
                elif ret_type == iap.ScriptReturnType.type_bytes:
                    result = {"_bytes": True}
                # stdout from ANSA goes to ANSA's own stdout, not captured here
                # so we synthesize it from the result
                if result:
                    stdout = json.dumps(result)
            else:
                ok = False
                error = (
                    f"IAP execution failed: ResultCode={resp.get_result_code()}, "
                    f"Details={resp.get_script_execution_details()}"
                )
        except Exception as exc:
            ok = False
            error = str(exc)

        ended_at = time.time()

        record = RunRecord(
            run_id=str(uuid.uuid4()),
            label=label,
            code=code,
            started_at=started_at,
            ended_at=ended_at,
            ok=ok,
            stdout=stdout,
            stderr="",
            error=error,
            result=result,
            session_id=self._session.session_id,
        )

        self._last_record = record
        self._write_log(record)
        return record

    def exec_file(self, filepath: str, label: str | None = None) -> RunRecord:
        """Execute a Python script file inside the active ANSA session."""
        if self._session is None or self._connection is None:
            raise RuntimeError("No active session. Call launch() or connect() first.")

        iap = _get_iap_module()

        if label is None:
            label = Path(filepath).name

        started_at = time.time()
        stdout = ""
        error = None
        result = None
        ok = True

        try:
            resp = self._connection.run_script_file(
                filepath,
                "main",
                iap.PreExecutionDatabaseAction.keep_database,
            )
            if resp.success():
                ret_type = resp.get_script_return_type()
                if ret_type == iap.ScriptReturnType.string_dict:
                    result = resp.get_response_dict()
                if result:
                    stdout = json.dumps(result)
            else:
                ok = False
                error = (
                    f"IAP execution failed: ResultCode={resp.get_result_code()}, "
                    f"Details={resp.get_script_execution_details()}"
                )
        except Exception as exc:
            ok = False
            error = str(exc)

        ended_at = time.time()

        record = RunRecord(
            run_id=str(uuid.uuid4()),
            label=label,
            code=f"# exec_file: {filepath}",
            started_at=started_at,
            ended_at=ended_at,
            ok=ok,
            stdout=stdout,
            stderr="",
            error=error,
            result=result,
            session_id=self._session.session_id,
        )

        self._last_record = record
        self._write_log(record)
        return record

    # ── properties ───────────────────────────────────────────────────────────

    @property
    def active_session(self) -> SessionInfo | None:
        return self._session

    @property
    def last_record(self) -> RunRecord | None:
        return self._last_record

    @property
    def is_connected(self) -> bool:
        return self._session is not None and self._connection is not None

    # ── internal ─────────────────────────────────────────────────────────────

    def _kill_process(self) -> None:
        if self._process is not None:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None

    def _write_log(self, record: RunRecord) -> None:
        runs_dir = self._sim_dir / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        log_path = runs_dir / f"{record.run_id}.json"
        log_path.write_text(json.dumps(record.to_dict(), indent=2))
