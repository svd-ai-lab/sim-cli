"""PyBaMM runner — pure Python, no native subprocess.

Lives inside .sim/envs/pybamm_<XX>_x/. Spawned via:

    <env-python> -m sim._runners.pybamm.runner

with SIM_RUNNER_PROFILE in the env so the runner self-binds to a yaml profile.

PyBaMM is the simplest runner in the family: there is no JVM, no remote
server, no shell environment to source. op_connect just imports pybamm
into the runner's namespace; op_exec runs snippets with `pybamm`,
`session` (a dict the user can use as scratchpad), and `_result` in scope.

If pybamm 26.x ever lands a breaking API change, ship a sibling module
(e.g. sim._runners.pybamm.runner_26) with its own concrete class and point
the matching profile's runner_module field at it. Until that happens,
one runner serves all currently-supported pybamm versions.
"""
from __future__ import annotations

import io
import os
import sys
import time
import traceback
import uuid
from contextlib import redirect_stderr, redirect_stdout
from typing import Any

from sim._runners.base import RunnerError, RunnerLoop


class PyBaMMRunner(RunnerLoop):
    """Single concrete runner for the pybamm family.

    Validated against pybamm 24.x and 25.x — no behavioral divergence
    yet. If a future major bump breaks anything, subclass and override
    op_handshake / op_exec rather than threading version-conditionals.
    """

    profile_name = "<unset>"

    def __init__(self) -> None:
        super().__init__()
        self._pybamm: Any = None
        self._session_state: dict[str, Any] = {}
        self._session_id: str | None = None
        self._runs: list[dict] = []

    @property
    def _sdk_version(self) -> str:
        return getattr(self._pybamm, "__version__", "unknown") if self._pybamm else "?"

    # ── op_handshake ────────────────────────────────────────────────────

    def op_handshake(self, args: dict) -> dict:
        try:
            import pybamm
        except ImportError as e:
            raise RunnerError(
                f"`pybamm` import failed inside profile env: {e}",
                type="SDKImportError",
            ) from e
        self._pybamm = pybamm
        return {
            "sdk_version": self._sdk_version,
            "solver_version": self._sdk_version,   # pybamm IS the solver
            "profile": self.profile_name,
        }

    # ── op_connect / op_disconnect ──────────────────────────────────────

    def op_connect(self, args: dict) -> dict:
        if self._session_id is not None:
            raise RunnerError("session already active")
        self._session_id = str(uuid.uuid4())
        self._session_state = {}
        return {
            "session_id": self._session_id,
            "mode": "in-process",
            "source": "import",
            "profile": self.profile_name,
            "sdk_version": self._sdk_version,
            "solver_version": self._sdk_version,
        }

    def op_disconnect(self, args: dict) -> dict:
        if self._session_id is None:
            return {"already_disconnected": True}
        sid = self._session_id
        self._session_id = None
        self._session_state = {}
        return {"session_id": sid, "disconnected": True}

    # ── op_exec / op_inspect ────────────────────────────────────────────

    def op_exec(self, args: dict) -> dict:
        if self._session_id is None:
            raise RunnerError("no active session — call op=connect first")

        code = args.get("code") or ""
        label = args.get("label") or "snippet"

        namespace: dict[str, Any] = {
            "pybamm": self._pybamm,
            "session": self._session_state,
            "_result": None,
        }

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        started = time.time()
        ok = True
        error = None

        try:
            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                exec(code, namespace)  # noqa: S102
        except Exception:
            ok = False
            error = traceback.format_exc()

        elapsed = round(time.time() - started, 4)
        record = {
            "run_id": str(uuid.uuid4()),
            "session_id": self._session_id,
            "label": label,
            "ok": ok,
            "stdout": stdout_buf.getvalue(),
            "stderr": stderr_buf.getvalue(),
            "error": error,
            "result": namespace.get("_result"),
            "elapsed_s": elapsed,
        }
        self._runs.append(record)
        return record

    def op_inspect(self, args: dict) -> dict:
        name = args.get("name") or "session.summary"

        if name == "session.versions":
            return {
                "sdk": {"name": "pybamm", "version": self._sdk_version},
                "solver": {"name": "pybamm", "version": self._sdk_version},
                "profile": self.profile_name,
            }
        if name == "session.summary":
            return {
                "session_id": self._session_id,
                "mode": "in-process",
                "profile": self.profile_name,
                "run_count": len(self._runs),
                "connected": self._session_id is not None,
                "session_state_keys": sorted(self._session_state.keys()),
            }
        if name == "last.result":
            if not self._runs:
                return {"has_last_run": False}
            return {"has_last_run": True, **self._runs[-1]}
        raise RunnerError(f"unknown inspect target: {name}", type="UnknownInspect")


def main() -> int:
    profile = os.environ.get("SIM_RUNNER_PROFILE")
    if not profile:
        sys.stderr.write(
            "[pybamm_runner] SIM_RUNNER_PROFILE not set — "
            "this runner is meant to be spawned by sim-cli's env_manager.\n"
        )
        return 2
    runner = PyBaMMRunner()
    runner.profile_name = profile
    return runner.run()


if __name__ == "__main__":
    sys.exit(main())
