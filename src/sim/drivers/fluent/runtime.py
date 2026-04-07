"""Session registry, snippet executor, and run log writer for PyFluent driver."""
from __future__ import annotations

import io
import json
import time
import traceback
import uuid
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from sim.drivers.fluent.schemas import RunRecord, SessionInfo


class PyFluentRuntime:
    """Manages the active PyFluent session and all run records."""

    def __init__(self, sim_dir: Path | None = None):
        self._sim_dir = sim_dir or (Path.cwd() / ".sim")
        self._sessions: dict[str, SessionInfo] = {}
        self._active_id: str | None = None
        self._last_record: RunRecord | None = None

    # ── session management ───────────────────────────────────────────────────────

    def register_session(
        self,
        session_id: str,
        mode: str,
        source: str,
        session: object,
    ) -> SessionInfo:
        """Register a live session and mark it as active."""
        info = SessionInfo(
            session_id=session_id,
            mode=mode,
            source=source,
            session=session,
        )
        self._sessions[session_id] = info
        self._active_id = session_id
        return info

    @property
    def active_session_id(self) -> str | None:
        return self._active_id

    def get_active_session(self) -> SessionInfo | None:
        if self._active_id is None:
            return None
        return self._sessions.get(self._active_id)

    # ── snippet execution ────────────────────────────────────────────────────────

    def exec_snippet(self, code: str, label: str = "pyfluent-snippet") -> RunRecord:
        """
        Execute a Python code snippet inside the active session context.

        Injects: session, solver, meshing, _result into the execution namespace.
        Captures stdout/stderr. Writes a JSON log to .sim/runs/<uuid>.json.
        """
        info = self.get_active_session()
        if info is None:
            raise RuntimeError("No active session. Call register_session() first.")

        session = info.session
        namespace: dict = {
            "session": session,
            "solver": session if info.mode == "solver" else None,
            "meshing": session if info.mode == "meshing" else None,
            "_result": None,
        }

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        error: str | None = None
        ok = True
        started_at = time.time()

        try:
            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                exec(code, namespace)  # noqa: S102
        except Exception:
            ok = False
            error = traceback.format_exc()

        ended_at = time.time()

        record = RunRecord(
            run_id=str(uuid.uuid4()),
            label=label,
            code=code,
            started_at=started_at,
            ended_at=ended_at,
            ok=ok,
            stdout=stdout_buf.getvalue(),
            stderr=stderr_buf.getvalue(),
            error=error,
            result=namespace.get("_result"),
            session_id=info.session_id,
            solver_kind=info.mode,
        )

        self._last_record = record
        self._write_log(record)
        return record

    @property
    def last_record(self) -> RunRecord | None:
        return self._last_record

    # ── log persistence ──────────────────────────────────────────────────────────

    def _write_log(self, record: RunRecord) -> None:
        runs_dir = self._sim_dir / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        log_path = runs_dir / f"{record.run_id}.json"
        log_path.write_text(json.dumps(record.to_dict(), indent=2))
