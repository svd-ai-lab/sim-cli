"""Core abstractions for sim drivers."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


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
