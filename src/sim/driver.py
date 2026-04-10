"""Core abstractions for sim drivers."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class SolverInstall:
    """One detected solver installation on a host.

    Returned in lists by ``DriverProtocol.detect_installed()``. Pure data;
    no SDK import required to construct or serialize.
    """
    name: str            # driver name, e.g. "fluent"
    version: str         # detected solver version, normalized e.g. "25.2"
    path: str            # filesystem path to the installation root
    source: str          # how we found it: "env:AWP_ROOT252" / "registry" / "default-path"
    extra: dict = field(default_factory=dict)  # driver-specific metadata

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "path": self.path,
            "source": self.source,
            "extra": dict(self.extra),
        }


@dataclass
class Diagnostic:
    level: str  # "error", "warning", "info"
    message: str
    line: int | None = None


@dataclass
class LintResult:
    ok: bool
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "diagnostics": [
                {"level": d.level, "message": d.message, "line": d.line}
                for d in self.diagnostics
            ],
        }


@dataclass
class RunResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float
    script: str
    solver: str
    timestamp: str

    def to_dict(self) -> dict:
        return {
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_s": self.duration_s,
            "script": self.script,
            "solver": self.solver,
            "timestamp": self.timestamp,
        }


@dataclass
class ConnectionInfo:
    solver: str
    version: str | None
    status: str  # "ok", "not_installed", "error"
    message: str = ""
    solver_version: str | None = None

    def to_dict(self) -> dict:
        d = {
            "solver": self.solver,
            "version": self.version,
            "status": self.status,
            "message": self.message,
        }
        if self.solver_version:
            d["solver_version"] = self.solver_version
        return d


@runtime_checkable
class DriverProtocol(Protocol):
    @property
    def name(self) -> str: ...
    def detect(self, script: Path) -> bool: ...
    def lint(self, script: Path) -> LintResult: ...
    def connect(self) -> ConnectionInfo: ...
    def parse_output(self, stdout: str) -> dict: ...
    def run_file(self, script: Path) -> RunResult: ...

    def detect_installed(self) -> list[SolverInstall]:
        """Scan THIS host for installations of this driver's solver.

        Pure Python. Must NOT import the SDK. Must NOT launch the solver.
        Must be safe to call when nothing is installed (returns []).
        Should be cheap (≤ a few hundred ms) — runs in interactive paths.

        See docs/architecture/version-compat.md §7 for the contract.
        Drivers that have not yet implemented this should return [] so the
        protocol stays runtime_checkable for partial migrations.
        """
        ...

    # -- Session lifecycle (optional) ----------------------------------------
    # Drivers that support persistent sessions (connect/exec/disconnect)
    # must set supports_session = True and implement launch/run/disconnect.

    @property
    def supports_session(self) -> bool:
        """Whether this driver supports persistent sessions."""
        ...

    def launch(self, **kwargs) -> dict:
        """Start a persistent solver session.

        Returns dict with at minimum ``{"ok": True, "session_id": "..."}``.
        Accepts keyword arguments from the connect request; each driver
        picks what it needs and ignores the rest.
        """
        ...

    def run(self, code: str, label: str = "") -> dict:
        """Execute code in the active session.

        Returns dict with at minimum ``{"ok": bool}``.
        """
        ...

    def disconnect(self) -> dict:
        """Tear down the active session. Must be idempotent.

        Returns ``{"ok": True, "disconnected": True}``.
        """
        ...
