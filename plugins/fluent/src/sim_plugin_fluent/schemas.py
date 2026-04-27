"""Shared dataclasses for the PyFluent driver."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SessionInfo:
    session_id: str
    mode: str       # "meshing" | "solver"
    source: str     # "launch" | "connection"
    session: object  # live pyfluent session object (not serialised)

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "session_id": self.session_id,
            "mode": self.mode,
            "source": self.source,
        }


@dataclass
class RunRecord:
    run_id: str
    label: str
    code: str
    started_at: float
    ended_at: float
    ok: bool
    stdout: str
    stderr: str
    error: str | None
    result: object  # whatever the user assigned to _result
    session_id: str
    solver_kind: str  # "meshing" | "solver"

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "label": self.label,
            "code": self.code,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "ok": self.ok,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "error": self.error,
            "result": self.result,
            "session_id": self.session_id,
            "solver_kind": self.solver_kind,
        }

    def to_run_result(self) -> dict:
        """Compact result dict returned to callers of driver.run()."""
        return {
            "run_id": self.run_id,
            "ok": self.ok,
            "label": self.label,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "error": self.error,
            "result": self.result,
        }
