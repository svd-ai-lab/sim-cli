"""OpenFOAM driver for sim.

OpenFOAM runs on a remote Linux machine. This driver communicates with
it via sim-server (HTTP). No local OpenFOAM installation needed.

Two execution models:

Phase 1 — One-shot local:
    run_file(script) executes a Python script locally via subprocess.
    Only useful if OpenFOAM is installed on the same machine.

Phase 2 — Remote session via sim-server:
    launch(host, port)   → POST /connect  {solver: "openfoam"}
    run(code, label)     → POST /exec     {code, label}
    query(name)          → GET  /inspect/<name>
    disconnect()         → POST /disconnect

The ``#!openfoam`` shebang in code sent to /exec triggers shell-mode
execution on the remote server — the code is run as a bash script
with the OpenFOAM environment sourced, not as Python.
"""
from __future__ import annotations

import ast
import json
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

from sim.driver import ConnectionInfo, Diagnostic, LintResult, RunResult


# ---------------------------------------------------------------------------
# Detection helpers (for local OpenFOAM, if present)
# ---------------------------------------------------------------------------

_OPENFOAM_PATTERNS = re.compile(
    r"(#\s*openfoam|#!openfoam|blockMesh|simpleFoam|icoFoam|pisoFoam"
    r"|snappyHexMesh|OpenFOAMCase|foam\.run_command|foam\.solve)",
    re.IGNORECASE,
)


class OpenFOAMDriver:
    """Sim driver for OpenFOAM (remote via sim-server).

    DriverProtocol surface:
        name, detect, lint, connect, parse_output, run_file

    Extended remote-session API:
        launch(host, port) → connect to remote sim-server
        run(code, label)   → execute on remote (shell or Python)
        query(name)        → inspect remote session state
        disconnect()       → tear down remote session
    """

    def __init__(self):
        self._host: str | None = None
        self._port: int | None = None
        self._session_id: str | None = None
        self._client: httpx.Client | None = None
        self._timeout: float = 300.0  # solver can run minutes

    @property
    def name(self) -> str:
        return "openfoam"

    # -- DriverProtocol -------------------------------------------------------

    def detect(self, script: Path) -> bool:
        """Detect OpenFOAM scripts.

        Accepts:
        - .foam files (OpenFOAM case markers)
        - .py files with OpenFOAM-related imports/comments
        - Shell scripts with #!openfoam shebang
        """
        ext = script.suffix.lower()
        if ext == ".foam":
            return True
        if ext in (".py", ".sh"):
            try:
                header = script.read_bytes()[:4096].decode("utf-8", errors="replace")
                return bool(_OPENFOAM_PATTERNS.search(header))
            except OSError:
                return False
        return False

    def lint(self, script: Path) -> LintResult:
        """Validate script syntax without executing."""
        ext = script.suffix.lower()

        if ext == ".foam":
            return LintResult(ok=True, diagnostics=[
                Diagnostic(level="info", message="OpenFOAM case marker file")
            ])

        if ext == ".sh":
            # Shell scripts — just check file exists and is non-empty
            try:
                text = script.read_text(errors="replace")
                if not text.strip():
                    return LintResult(ok=False, diagnostics=[
                        Diagnostic(level="error", message="Script is empty")
                    ])
                return LintResult(ok=True, diagnostics=[])
            except OSError as e:
                return LintResult(ok=False, diagnostics=[
                    Diagnostic(level="error", message=f"Cannot read file: {e}")
                ])

        if ext == ".py":
            try:
                text = script.read_text(errors="replace")
                ast.parse(text)
                return LintResult(ok=True, diagnostics=[])
            except SyntaxError as e:
                return LintResult(ok=False, diagnostics=[
                    Diagnostic(level="error", message=f"Syntax error: {e}", line=e.lineno)
                ])

        return LintResult(ok=False, diagnostics=[
            Diagnostic(level="error", message=f"Unsupported file type '{ext}'")
        ])

    def connect(self) -> ConnectionInfo:
        """Check remote sim-server availability (if host/port set) or local OF."""
        if self._host:
            try:
                r = httpx.get(
                    f"http://{self._host}:{self._port}/ps",
                    timeout=5.0,
                )
                data = r.json()
                return ConnectionInfo(
                    solver="openfoam",
                    version=data.get("openfoam_version", "remote"),
                    status="ok",
                    message=f"sim-server at {self._host}:{self._port} reachable",
                )
            except Exception as e:
                return ConnectionInfo(
                    solver="openfoam",
                    version=None,
                    status="unreachable",
                    message=f"Cannot reach sim-server at {self._host}:{self._port}: {e}",
                )

        # No remote host set — report as needing configuration
        return ConnectionInfo(
            solver="openfoam",
            version=None,
            status="not_configured",
            message="OpenFOAM runs remotely. Call launch(host, port) to connect to sim-server.",
        )

    def parse_output(self, stdout: str) -> dict:
        """Extract last JSON object from stdout."""
        for line in reversed(stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        return {}

    def run_file(self, script: Path) -> RunResult:
        """Execute a local Python script (fallback for local OF installs)."""
        from sim.runner import run_subprocess
        return run_subprocess(
            [sys.executable, str(script)],
            script=script,
            solver=self.name,
        )

    # -- Phase 2: Remote session via sim-server --------------------------------

    def launch(
        self,
        host: str = "localhost",
        port: int = 7600,
        timeout: float = 300.0,
    ) -> dict:
        """Connect to a remote sim-server running OpenFOAM.

        Args:
            host: sim-server hostname or IP.
            port: sim-server port (default 7600).
            timeout: HTTP timeout for long-running solver commands.
        """
        if self._session_id is not None:
            raise RuntimeError("Session already active. Call disconnect() first.")

        self._host = host
        self._port = port
        self._timeout = timeout
        self._client = httpx.Client(timeout=timeout)

        try:
            r = self._client.post(
                f"http://{host}:{port}/connect",
                json={"solver": "openfoam"},
            )
        except httpx.ConnectError as e:
            self._client.close()
            self._client = None
            raise RuntimeError(f"Cannot reach sim-server at {host}:{port}: {e}")

        if r.status_code != 200:
            detail = r.json().get("detail", r.text)
            raise RuntimeError(f"sim-server /connect failed: {detail}")

        data = r.json()
        self._session_id = data.get("data", {}).get("session_id")
        return data

    def run(self, code: str, label: str = "openfoam-snippet") -> dict:
        """Execute code on the remote OpenFOAM session.

        If code starts with ``#!openfoam``, the server runs it as a
        shell script with the OpenFOAM environment sourced.
        Otherwise, it runs as Python code.

        Args:
            code: Shell commands (with #!openfoam prefix) or Python code.
            label: Human-readable label for this execution step.
        """
        if self._client is None:
            raise RuntimeError("Not connected. Call launch() first.")

        r = self._client.post(
            f"http://{self._host}:{self._port}/exec",
            json={"code": code, "label": label},
        )

        if r.status_code != 200:
            detail = r.json().get("detail", r.text)
            return {"ok": False, "label": label, "error": detail}

        data = r.json()
        return data.get("data", data)

    def query(self, name: str = "session.summary") -> dict:
        """Query remote session state.

        Supported: "session.summary", "last.result"
        """
        if self._client is None:
            raise RuntimeError("Not connected. Call launch() first.")

        r = self._client.get(
            f"http://{self._host}:{self._port}/inspect/{name}",
        )
        data = r.json()
        return data.get("data", data)

    def disconnect(self) -> dict:
        """Disconnect from the remote sim-server session."""
        result = {"ok": False, "reason": "no active session"}

        if self._client is not None:
            try:
                r = self._client.post(
                    f"http://{self._host}:{self._port}/disconnect",
                )
                result = r.json()
            except Exception:
                pass
            try:
                self._client.close()
            except Exception:
                pass

        self._client = None
        self._session_id = None
        return result

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._session_id is not None

    def ps(self) -> dict:
        """Check remote session status."""
        if self._client is None:
            return {"connected": False}
        try:
            r = self._client.get(f"http://{self._host}:{self._port}/ps")
            return r.json()
        except Exception:
            return {"connected": False, "error": "request failed"}
