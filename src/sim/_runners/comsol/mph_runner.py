"""COMSOL runner — `mph` Python binding inside a profile env.

Lives inside .sim/envs/comsol_<version>_mph_<X>/. Spawned via:

    <env-python> -m sim._runners.comsol.mph_runner

with SIM_RUNNER_PROFILE in the env so the runner self-binds to a yaml profile.

Wire protocol:
  handshake -> import mph, report mph version + COMSOL backend version
  connect   -> mph.start() (or mph.Client()) — launches comsolmphserver
               under the hood and creates an empty model
  exec      -> exec(code) with `client`, `model`, `mph` in namespace
  inspect   -> session.summary, session.versions, last.result
  disconnect-> client.disconnect() / client.exit()

The COMSOL backend is discovered by `mph` itself (it walks the registry on
Windows and the standard /usr/local prefix on Linux). When the user has
multiple COMSOL versions installed and wants a specific one, set
COMSOL_ROOT in the runner's env before connect; mph respects it.
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


def _safe_model_id(model: Any) -> str | None:
    """Best-effort identifier for an mph.Model. Different mph versions
    expose `.name()`, `.tag` (attribute), or only the underlying Java
    object — try each before giving up."""
    if model is None:
        return None
    for attr, call in (("name", True), ("tag", True), ("tag", False)):
        try:
            v = getattr(model, attr)
            return str(v() if call and callable(v) else v)
        except Exception:
            continue
    try:
        java = getattr(model, "java", None)
        if java is not None and hasattr(java, "tag"):
            return str(java.tag())
    except Exception:
        pass
    return repr(model)


class ComsolMphRunner(RunnerLoop):
    """SDK-bound COMSOL runner. profile_name is set from SIM_RUNNER_PROFILE."""

    profile_name = "<unset>"

    def __init__(self) -> None:
        super().__init__()
        self._mph: Any = None              # the imported `mph` module
        self._client: Any = None            # mph.Client
        self._model: Any = None             # active mph.Model
        self._session_id: str | None = None
        self._runs: list[dict] = []
        self._sdk_version: str = "?"
        self._solver_version: str = "?"
        self._backend: dict | None = None

    # ── handshake ────────────────────────────────────────────────────────

    def op_handshake(self, args: dict) -> dict:
        try:
            import mph
        except ImportError as e:
            raise RunnerError(
                f"`mph` import failed inside profile env: {e}",
                type="SDKImportError",
            ) from e

        self._mph = mph
        self._sdk_version = getattr(mph, "__version__", "unknown")

        # Best-effort COMSOL backend discovery without launching anything.
        # mph.discovery.backend() returns a dict with keys including 'name'
        # and 'version'. It walks the registry / install dirs only — does
        # NOT spawn comsolmphserver — so it's cheap to call.
        try:
            backend = mph.discovery.backend()
            if isinstance(backend, dict):
                self._backend = backend
                ver = backend.get("name") or backend.get("version") or "?"
                # 'name' looks like 'COMSOL Multiphysics 6.4'; pull X.Y out
                import re as _re
                m = _re.search(r"(\d+\.\d+)", str(ver))
                self._solver_version = m.group(1) if m else str(ver)
        except Exception:
            # Fall back to nothing; op_connect will surface a clearer error
            self._backend = None
            self._solver_version = "?"

        return {
            "sdk_version": self._sdk_version,
            "solver_version": self._solver_version,
            "profile": self.profile_name,
            "backend": self._backend,
        }

    # ── connect / disconnect ────────────────────────────────────────────

    def op_connect(self, args: dict) -> dict:
        if self._client is not None:
            raise RunnerError("session already active")

        ui_mode = args.get("ui_mode", "no_gui")
        # mph.start(...) starts a stand-alone client (no separate server).
        # `cores` controls multithreading; default to 1 for predictability.
        cores = int(args.get("processors") or 1)

        try:
            # mph 1.x: mph.start(cores=N) → returns a Client
            self._client = self._mph.start(cores=cores)
        except Exception as e:
            raise RunnerError(
                f"mph.start failed: {type(e).__name__}: {e}",
                type="LaunchFailure",
            ) from e

        # Create an empty model so the snippet namespace has something
        # meaningful by default. Snippets are free to .clear() or load
        # their own .mph file.
        try:
            self._model = self._client.create("Model1")
        except Exception:
            # Some mph versions return None until first model — that's OK
            self._model = None

        self._session_id = str(uuid.uuid4())

        return {
            "session_id": self._session_id,
            "mode": "client",
            "source": "mph.start",
            "ui_mode": ui_mode,
            "profile": self.profile_name,
            "sdk_version": self._sdk_version,
            "solver_version": self._solver_version,
            "model_tag": _safe_model_id(self._model),
        }

    def op_disconnect(self, args: dict) -> dict:
        if self._client is None:
            return {"already_disconnected": True}
        sid = self._session_id
        try:
            # mph.Client has .clear() to drop models then .disconnect() to
            # release the JVM-side server. Some versions only expose
            # .disconnect() — try in order.
            if hasattr(self._client, "clear"):
                try:
                    self._client.clear()
                except Exception:
                    pass
            if hasattr(self._client, "disconnect"):
                self._client.disconnect()
        except Exception:
            pass
        self._client = None
        self._model = None
        self._session_id = None
        return {"session_id": sid, "disconnected": True}

    # ── exec / inspect ──────────────────────────────────────────────────

    def op_exec(self, args: dict) -> dict:
        if self._client is None:
            raise RunnerError("no active session — call op=connect first")

        code = args.get("code") or ""
        label = args.get("label") or "snippet"

        namespace: dict[str, Any] = {
            "mph": self._mph,
            "client": self._client,
            "model": self._model,
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

        # If the snippet swapped in a different model, track it. Also
        # refresh from client.models() — snippets that call client.clear()
        # + client.load(...) put the new model in the client's list but
        # leave the local `model` reference stale.
        if namespace.get("model") is not None and namespace.get("model") is not self._model:
            self._model = namespace["model"]
        else:
            try:
                models = list(self._client.models())
                if models and models[0] is not self._model:
                    self._model = models[0]
                elif not models:
                    self._model = None
            except Exception:
                pass

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
                "sdk": {"name": "mph", "version": self._sdk_version},
                "solver": {"name": "comsol", "version": self._solver_version},
                "profile": self.profile_name,
                "backend": self._backend,
            }
        if name == "session.summary":
            # Recompute model id defensively — _safe_model_id may touch a
            # stale Java handle if a snippet replaced the model since the
            # last exec; fall back to None on any error.
            try:
                model_id = _safe_model_id(self._model)
            except Exception:
                model_id = None
            return {
                "session_id": self._session_id,
                "mode": "client",
                "profile": self.profile_name,
                "run_count": len(self._runs),
                "connected": self._client is not None,
                "model_tag": model_id,
            }
        if name == "last.result":
            if not self._runs:
                return {"has_last_run": False}
            return {"has_last_run": True, **self._runs[-1]}
        raise RunnerError(f"unknown inspect target: {name}", type="UnknownInspect")


def main() -> int:
    profile = os.environ.get("SIM_RUNNER_PROFILE", "comsol_64_mph_1")
    runner = ComsolMphRunner()
    runner.profile_name = profile
    return runner.run()


if __name__ == "__main__":
    sys.exit(main())
