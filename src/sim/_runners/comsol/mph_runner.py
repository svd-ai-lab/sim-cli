"""COMSOL runner — `mph` Python binding inside a profile env.

Lives inside .sim/envs/comsol_<version>_mph_<X>/. Spawned via:

    <env-python> -m sim._runners.comsol.mph_runner

with SIM_RUNNER_PROFILE in the env so the runner self-binds to a yaml profile.

═══════════════════════════════════════════════════════════════════════════
ARCHITECTURE — base class + per-version subclasses + registry dispatch
═══════════════════════════════════════════════════════════════════════════

`ComsolMphRunner` is an *abstract* RunnerLoop subclass. Every operation that
might change between mph / COMSOL versions is exposed as a clearly named
hook method:

    _start_client(mph, cores)        → mph.Client
    _create_default_model(client)    → mph.Model | None
    _identify_model(model)           → str | None     (model tag/name/id)
    _refresh_model(client, current)  → mph.Model | None
    _disconnect_client(client)       → None           (lifecycle teardown)
    _query_solver_backend(mph)       → (version_str, backend_dict)

The default implementations for mph 1.x ship as ``Mph1Runner`` below. They
match the API surface mph exposed throughout 1.2.x–1.3.x and are validated
against COMSOL 6.4.

═══════════════════════════════════════════════════════════════════════════
EXTENDING for a new mph or COMSOL version
═══════════════════════════════════════════════════════════════════════════

When mph 2.x ships and breaks something:

    1. Subclass ComsolMphRunner (or Mph1Runner if most behavior carries):

           class Mph2Runner(ComsolMphRunner):
               variant = "mph_2"

               def _start_client(self, mph, cores):
                   return mph.start(processors=cores)   # renamed in 2.x

               def _identify_model(self, model):
                   return str(model.name())             # 2.x dropped .tag
               # everything else inherited

    2. Either switch this module's main() to the new class, or (cleaner)
       ship Mph2Runner in a sibling module sim._runners.comsol.mph2_runner.
    3. Add a new profile in compatibility.yaml whose `runner_module` field
       points at the new module. The validated mph 1.x code path stays
       byte-identical.

═══════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import io
import os
import re
import sys
import time
import traceback
import uuid
from contextlib import redirect_stderr, redirect_stdout
from typing import Any

from sim._runners.base import RunnerError, RunnerLoop


# ─── abstract base ──────────────────────────────────────────────────────────


class ComsolMphRunner(RunnerLoop):
    """Abstract COMSOL runner. Subclasses set ``variant`` and override hooks.

    The base class implements the JSON-over-stdio protocol and the
    op_handshake / op_connect / op_exec / op_inspect / op_disconnect
    handlers. The version-sensitive bits are delegated to instance methods
    starting with ``_`` (the "hooks") so subclasses can override them
    without re-implementing the protocol layer.
    """

    profile_name = "<unset>"
    variant: str = "abstract"   # subclasses set this

    def __init__(self) -> None:
        super().__init__()
        self._mph: Any = None
        self._client: Any = None
        self._model: Any = None
        self._session_id: str | None = None
        self._runs: list[dict] = []
        # Cached after first handshake — backend probe touches the registry
        # so we don't want to re-run it on every inspect call.
        self._solver_version: str = "?"
        self._backend: dict | None = None

    @property
    def _sdk_version(self) -> str:
        return getattr(self._mph, "__version__", "unknown") if self._mph else "?"

    # ── version-sensitive hooks (override in subclass) ──────────────────

    def _start_client(self, mph: Any, cores: int) -> Any:
        """Launch the mph Client. Override per mph major version."""
        raise NotImplementedError

    def _create_default_model(self, client: Any) -> Any:
        """Create the empty default model after connect. May return None."""
        raise NotImplementedError

    def _identify_model(self, model: Any) -> str | None:
        """Return a string identifier for an mph.Model (tag/name/id)."""
        raise NotImplementedError

    def _refresh_model(self, client: Any, current: Any) -> Any:
        """Re-pick the active model after a snippet (load/clear/etc).

        Default: take the first model in client.models() if any. Override
        if mph changes how models are enumerated.
        """
        try:
            models = list(client.models())
        except Exception:
            return current
        return models[0] if models else None

    def _disconnect_client(self, client: Any) -> None:
        """Tear down the client. Best-effort; exceptions swallowed."""
        raise NotImplementedError

    def _query_solver_backend(self, mph: Any) -> tuple[str, dict | None]:
        """Probe the COMSOL backend WITHOUT launching it. Cheap, optional.

        Returns (solver_version_short, backend_dict_or_none). On failure
        return ("?", None) — handshake will still succeed.
        """
        return ("?", None)

    # ── op_handshake ────────────────────────────────────────────────────

    def op_handshake(self, args: dict) -> dict:
        try:
            import mph
        except ImportError as e:
            raise RunnerError(
                f"`mph` import failed inside profile env: {e}",
                type="SDKImportError",
            ) from e

        self._mph = mph
        try:
            self._solver_version, self._backend = self._query_solver_backend(mph)
        except Exception:
            self._solver_version, self._backend = ("?", None)

        return {
            "sdk_version": self._sdk_version,
            "solver_version": self._solver_version,
            "profile": self.profile_name,
            "variant": self.variant,
            "backend": self._backend,
        }

    # ── op_connect / op_disconnect ──────────────────────────────────────

    def op_connect(self, args: dict) -> dict:
        if self._client is not None:
            raise RunnerError("session already active")

        ui_mode = args.get("ui_mode", "no_gui")
        cores = int(args.get("processors") or 1)

        try:
            self._client = self._start_client(self._mph, cores)
        except Exception as e:
            raise RunnerError(
                f"start_client failed: {type(e).__name__}: {e}",
                type="LaunchFailure",
            ) from e

        try:
            self._model = self._create_default_model(self._client)
        except Exception:
            self._model = None

        self._session_id = str(uuid.uuid4())

        return {
            "session_id": self._session_id,
            "mode": "client",
            "source": "mph.start",
            "ui_mode": ui_mode,
            "profile": self.profile_name,
            "variant": self.variant,
            "sdk_version": self._sdk_version,
            "solver_version": self._solver_version,
            "model_tag": self._safe_identify(self._model),
        }

    def op_disconnect(self, args: dict) -> dict:
        if self._client is None:
            return {"already_disconnected": True}
        sid = self._session_id
        try:
            self._disconnect_client(self._client)
        except Exception:
            pass
        self._client = None
        self._model = None
        self._session_id = None
        return {"session_id": sid, "disconnected": True}

    # ── op_exec / op_inspect ────────────────────────────────────────────

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

        # Track snippet model swaps; otherwise refresh from the client
        # (load/clear leave self._model dangling).
        ns_model = namespace.get("model")
        if ns_model is not None and ns_model is not self._model:
            self._model = ns_model
        else:
            try:
                self._model = self._refresh_model(self._client, self._model)
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
                "variant": self.variant,
                "backend": self._backend,
            }
        if name == "session.summary":
            return {
                "session_id": self._session_id,
                "mode": "client",
                "profile": self.profile_name,
                "variant": self.variant,
                "run_count": len(self._runs),
                "connected": self._client is not None,
                "model_tag": self._safe_identify(self._model),
            }
        if name == "last.result":
            if not self._runs:
                return {"has_last_run": False}
            return {"has_last_run": True, **self._runs[-1]}
        raise RunnerError(f"unknown inspect target: {name}", type="UnknownInspect")

    # ── helpers ─────────────────────────────────────────────────────────

    def _safe_identify(self, model: Any) -> str | None:
        """Wrap _identify_model so any Java exception degrades to None.

        Subclass hooks may touch a stale Java handle (e.g. after the
        snippet called client.clear()); we want inspect endpoints to
        return a clean None instead of crashing the whole RPC.
        """
        if model is None:
            return None
        try:
            return self._identify_model(model)
        except Exception:
            return None


# ─── default implementation: mph 1.x ────────────────────────────────────────


class Mph1Runner(ComsolMphRunner):
    """Concrete runner for mph 1.2.x–1.3.x. Validated against COMSOL 6.4.

    Override individual hooks here if a 1.x point release introduces a
    backward-incompatible change you want to absorb without bumping the
    profile to a new variant.
    """

    variant = "mph_1"

    # ── lifecycle hooks ────────────────────────────────────────────────

    def _start_client(self, mph: Any, cores: int) -> Any:
        # mph 1.x: mph.start(cores=N) → returns a Client; under the hood
        # this boots the JVM and connects to comsolmphserver.
        return mph.start(cores=cores)

    def _create_default_model(self, client: Any) -> Any:
        try:
            return client.create("Model1")
        except Exception:
            return None

    def _disconnect_client(self, client: Any) -> None:
        # mph 1.x: clear() drops models, disconnect() releases the JVM-side
        # server. Some sub-versions only expose one of the two.
        if hasattr(client, "clear"):
            try:
                client.clear()
            except Exception:
                pass
        if hasattr(client, "disconnect"):
            client.disconnect()

    # ── identification ──────────────────────────────────────────────────

    def _identify_model(self, model: Any) -> str | None:
        # Validated against mph 1.2.x–1.3.x; _safe_identify above swallows
        # any exception (e.g. stale Java handle after client.clear()).
        return str(model.name())

    # ── backend probe ──────────────────────────────────────────────────

    def _query_solver_backend(self, mph: Any) -> tuple[str, dict | None]:
        try:
            backend = mph.discovery.backend()
        except Exception:
            return ("?", None)
        if not isinstance(backend, dict):
            return ("?", None)
        ver_field = backend.get("name") or backend.get("version") or "?"
        m = re.search(r"(\d+\.\d+)", str(ver_field))
        return (m.group(1) if m else str(ver_field), backend)


# ─── entry point ────────────────────────────────────────────────────────────
#
# This module ships exactly one concrete runner: Mph1Runner. To add support
# for mph 2.x or a hypothetical Comsol 7 with a divergent Java API, the
# pattern is:
#
#   - Subclass ComsolMphRunner (or Mph1Runner) overriding the changed hooks
#   - Either: ship it in this file and switch main() to instantiate it, OR
#     ship it as a brand-new module sim._runners.comsol.<name>_runner whose
#     main() instantiates the new class directly, then point the matching
#     profile's `runner_module` field at the new module path
#
# The latter is the preferred path — it keeps each profile's code path
# physically separated and avoids the indirection of a runtime registry.


def main() -> int:
    profile = os.environ.get("SIM_RUNNER_PROFILE")
    if not profile:
        sys.stderr.write(
            "[comsol_mph_runner] SIM_RUNNER_PROFILE not set — "
            "this runner is meant to be spawned by sim-cli's env_manager.\n"
        )
        return 2
    runner = Mph1Runner()
    runner.profile_name = profile
    return runner.run()


if __name__ == "__main__":
    sys.exit(main())
