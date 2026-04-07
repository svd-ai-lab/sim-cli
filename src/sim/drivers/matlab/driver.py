"""MATLAB driver for sim."""
from __future__ import annotations

import io
import json
import re
import shutil
import uuid
from pathlib import Path

from sim.driver import ConnectionInfo, Diagnostic, LintResult
from sim.runner import run_subprocess


class MatlabDriver:
    """MATLAB driver — one-shot and persistent session execution."""

    def __init__(self):
        self._engine = None
        self._session_id: str | None = None
        self._desktop: bool = False

    @property
    def name(self) -> str:
        return "matlab"

    def detect(self, script: Path) -> bool:
        """Treat `.m` files as MATLAB scripts."""
        return script.suffix.lower() == ".m"

    def lint(self, script: Path) -> LintResult:
        """Run MATLAB-native linting when MATLAB is available."""
        if not self.detect(script):
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(level="error", message="Not a MATLAB `.m` script")],
            )

        matlab = shutil.which("matlab")
        if matlab is None:
            return LintResult(
                ok=False,
                diagnostics=[
                    Diagnostic(
                        level="error",
                        message="MATLAB is not available on PATH; cannot lint `.m` files",
                    )
                ],
            )

        expr = (
            "issues = checkcode('{path}', '-id'); "
            "if isempty(issues), disp(jsonencode(struct('ok', true, 'diagnostics', {{}}))); "
            "else, msgs = strings(numel(issues), 1); "
            "for i = 1:numel(issues), msgs(i) = string(issues(i).message); end; "
            "payload = struct('ok', false, 'diagnostics', cellstr(msgs)); "
            "disp(jsonencode(payload)); end"
        ).format(path=_matlab_string(script.resolve()))

        result = run_subprocess(
            [matlab, "-batch", expr],
            script=script,
            solver=self.name,
        )
        if result.exit_code != 0:
            return LintResult(
                ok=False,
                diagnostics=[
                    Diagnostic(
                        level="error",
                        message=result.stderr or "MATLAB lint command failed",
                    )
                ],
            )

        payload = self.parse_output(result.stdout)
        diagnostics = [
            Diagnostic(level="warning", message=message)
            for message in payload.get("diagnostics", [])
        ]
        return LintResult(ok=payload.get("ok", not diagnostics), diagnostics=diagnostics)

    def connect(self) -> ConnectionInfo:
        """Check if MATLAB is available on PATH."""
        matlab = shutil.which("matlab")
        if matlab is None:
            return ConnectionInfo(
                solver="matlab",
                version=None,
                status="not_installed",
                message="matlab is not available on PATH",
            )

        return ConnectionInfo(
            solver="matlab",
            version=None,
            status="ok",
            message=f"matlab available at {matlab}",
        )

    def parse_output(self, stdout: str) -> dict:
        """Parse the last JSON object printed by a MATLAB script."""
        for line in reversed(stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        return {}

    def run_file(self, script: Path):
        """Execute a MATLAB `.m` script using MATLAB batch mode."""
        matlab = shutil.which("matlab")
        if matlab is None:
            raise RuntimeError("matlab is not available on PATH")

        expr = f"run('{_matlab_string(script.resolve())}')"
        return run_subprocess(
            [matlab, "-batch", expr],
            script=script,
            solver=self.name,
        )

    # ── Persistent session API ───────────────────────────────────────────────

    def launch(self, ui_mode: str = "desktop", **kwargs) -> dict:
        """Start a persistent MATLAB session via matlab.engine."""
        try:
            import matlab.engine  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError(
                "matlabengine is not installed. "
                "Run: pip install matlabengine"
            ) from exc

        self._desktop = ui_mode in ("desktop", "gui")
        if self._desktop:
            self._engine = matlab.engine.start_matlab("-desktop")
        else:
            self._engine = matlab.engine.start_matlab()

        self._session_id = str(uuid.uuid4())
        return {
            "ok": True,
            "session_id": self._session_id,
            "ui_mode": ui_mode,
        }

    def run(self, code: str, label: str = "snippet") -> dict:
        """Execute MATLAB code in the persistent session."""
        if self._engine is None:
            raise RuntimeError("No active MATLAB session.")

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        ok = True
        error = None

        try:
            self._engine.eval(code, nargout=0, stdout=stdout_buf, stderr=stderr_buf)
        except Exception as e:
            ok = False
            error = str(e)

        stdout = stdout_buf.getvalue()
        parsed = self.parse_output(stdout) if ok else None

        return {
            "ok": ok,
            "label": label,
            "stdout": stdout,
            "stderr": stderr_buf.getvalue(),
            "error": error,
            "result": parsed,
        }

    def query(self, name: str) -> dict:
        """Named query against the MATLAB session."""
        if name == "workspace.summary":
            if self._engine is None:
                return {"connected": False}
            variables = self._engine.eval("who", nargout=1)
            return {"connected": True, "variables": list(variables) if variables else []}

        if name == "session.summary":
            return {
                "connected": self._engine is not None,
                "session_id": self._session_id,
                "ui_mode": "desktop" if self._desktop else "headless",
            }

        return {"error": f"unknown query: {name}"}

    def disconnect(self) -> dict:
        """Shut down the MATLAB session."""
        if self._engine is None:
            return {"ok": False, "reason": "no active session"}
        sid = self._session_id
        try:
            self._engine.quit()
        except Exception:
            pass
        self._engine = None
        self._session_id = None
        return {"ok": True, "session_id": sid, "disconnected": True}


def _matlab_string(path: Path) -> str:
    """Convert a filesystem path to a MATLAB-quoted string literal."""
    text = path.as_posix()
    return re.sub(r"'", "''", text)
