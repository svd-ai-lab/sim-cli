"""Shared FluentRunner base used by every PyFluent profile entry point.

Each per-profile module (``pyfluent_037``, ``pyfluent_038``, …) just sets
``profile_name`` and the SDK version constraints, then calls ``run()``.
Profile-specific behavior (e.g. API name differences between PyFluent 0.37
and 0.38) lives in profile modules — this base only handles the parts that
are common across the whole PyFluent family.
"""
from __future__ import annotations

import io
import os
import time
import traceback
import uuid
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

from sim._runners.base import RunnerError, RunnerLoop


class FluentRunnerBase(RunnerLoop):
    """Common bits for every PyFluent profile runner.

    Subclasses MUST set:
        profile_name: str    — matches a profile in fluent/compatibility.yaml
    """

    profile_name = "<unset>"

    def __init__(self) -> None:
        super().__init__()
        self._pyfluent = None
        self._session: Any = None
        self._mode: str | None = None
        self._session_id: str | None = None
        self._runs: list[dict] = []
        self._sdk_version: str = "?"
        self._solver_version: str = "?"

    # ── handshake ────────────────────────────────────────────────────────

    def op_handshake(self, args: dict) -> dict:
        try:
            import ansys.fluent.core as pyfluent
        except ImportError as e:
            raise RunnerError(
                f"ansys-fluent-core import failed inside profile env: {e}",
                type="SDKImportError",
            ) from e

        self._pyfluent = pyfluent
        self._sdk_version = getattr(pyfluent, "__version__", "unknown")

        # Try to detect the Fluent version from the same env vars sim's
        # detector uses, so the handshake reports the actual binary that
        # this env will launch — not whatever is on PATH.
        self._solver_version = self._detect_solver_version_string()

        return {
            "sdk_version": self._sdk_version,
            "solver_version": self._solver_version,
            "profile": self.profile_name,
        }

    def _detect_solver_version_string(self) -> str:
        """Best-effort solver version reporting (without launching Fluent).

        Walks AWP_ROOT* env vars and returns the highest. The runner does
        NOT launch the solver here — that happens at op_connect time.
        """
        import re
        candidates: list[tuple[int, str]] = []
        for k, v in os.environ.items():
            m = re.match(r"AWP_ROOT(\d{3})$", k)
            if m and v:
                code = m.group(1)
                short = f"{code[:2]}.{code[2]}"
                candidates.append((int(code), short))
        if not candidates:
            return "unknown"
        candidates.sort(reverse=True)
        return candidates[0][1]

    # ── connect / disconnect ────────────────────────────────────────────

    def op_connect(self, args: dict) -> dict:
        if self._session is not None:
            raise RunnerError("session already active")

        mode = args.get("mode", "solver")
        ui_mode = args.get("ui_mode", "gui")
        processors = args.get("processors", 1)
        ip = args.get("ip")
        port = args.get("port")
        password = args.get("password")

        # When the user has Fluent 24R1 (v241) installed, PyFluent 0.38+
        # dropped support but PyFluent 0.37 still respects PYFLUENT_FLUENT_ROOT.
        # Set it from AWP_ROOT241 if present and the user hasn't.
        if not os.environ.get("PYFLUENT_FLUENT_ROOT"):
            awp241 = os.environ.get("AWP_ROOT241")
            if awp241:
                os.environ["PYFLUENT_FLUENT_ROOT"] = str(Path(awp241) / "fluent")

        pyfluent = self._pyfluent
        try:
            if ip and port:
                session = pyfluent.connect_to_fluent(
                    ip=ip, port=port, password=password or ""
                )
                source = "connection"
                mode = "solver"
            else:
                # Force pyfluent to bind to localhost so the server-info
                # localhost check passes (issue we've hit on 0.37.2).
                if hasattr(pyfluent, "config"):
                    if not pyfluent.config.launch_fluent_ip:
                        pyfluent.config.launch_fluent_ip = "127.0.0.1"

                if mode == "meshing":
                    session = pyfluent.launch_fluent(
                        mode="meshing",
                        ui_mode=ui_mode,
                        processor_count=processors,
                    )
                else:
                    session = pyfluent.launch_fluent(
                        ui_mode=ui_mode,
                        processor_count=processors,
                    )
                source = "launch"
        except Exception as e:
            raise RunnerError(
                f"launch_fluent failed: {type(e).__name__}: {e}",
                type="LaunchFailure",
            ) from e

        self._session = session
        self._mode = mode
        self._session_id = str(uuid.uuid4())

        return {
            "session_id": self._session_id,
            "mode": mode,
            "source": source,
            "profile": self.profile_name,
            "sdk_version": self._sdk_version,
        }

    def op_disconnect(self, args: dict) -> dict:
        if self._session is None:
            return {"already_disconnected": True}
        sid = self._session_id
        try:
            self._session.exit()
        except Exception:
            pass
        self._session = None
        self._mode = None
        self._session_id = None
        return {"session_id": sid, "disconnected": True}

    # ── exec / inspect ──────────────────────────────────────────────────

    def op_exec(self, args: dict) -> dict:
        if self._session is None:
            raise RunnerError("no active session — call op=connect first")

        code = args.get("code") or ""
        label = args.get("label") or "snippet"

        namespace: dict[str, Any] = {
            "session": self._session,
            "_result": None,
        }
        if self._mode == "meshing":
            namespace["meshing"] = self._session
        else:
            namespace["solver"] = self._session

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
        result = namespace.get("_result")

        record = {
            "run_id": str(uuid.uuid4()),
            "session_id": self._session_id,
            "label": label,
            "ok": ok,
            "stdout": stdout_buf.getvalue(),
            "stderr": stderr_buf.getvalue(),
            "error": error,
            "result": result,
            "elapsed_s": elapsed,
        }
        self._runs.append(record)
        return record

    def op_inspect(self, args: dict) -> dict:
        name = args.get("name") or "session.summary"

        if name == "session.versions":
            return {
                "sdk": {"name": "ansys-fluent-core", "version": self._sdk_version},
                "solver": {"name": "fluent", "version": self._solver_version},
                "profile": self.profile_name,
            }
        if name == "session.summary":
            return {
                "session_id": self._session_id,
                "mode": self._mode,
                "profile": self.profile_name,
                "run_count": len(self._runs),
                "connected": self._session is not None,
            }
        if name == "last.result":
            if not self._runs:
                return {"has_last_run": False}
            last = self._runs[-1]
            return {"has_last_run": True, **last}
        raise RunnerError(f"unknown inspect target: {name}", type="UnknownInspect")
