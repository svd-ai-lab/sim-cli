"""Shared dataclasses for the ANSA driver."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SessionInfo:
    session_id: str
    mode: str       # "batch" (always — ANSA is a pre-processor)
    source: str     # "launch" | "connection"
    port: int
    pid: int | None = None

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "session_id": self.session_id,
            "mode": self.mode,
            "source": self.source,
            "port": self.port,
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
    result: object          # dict returned by IAP (string_dict) or None
    session_id: str

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
