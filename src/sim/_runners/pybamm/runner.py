"""PyBaMM runner — pure Python, no native subprocess.

Lives inside .sim/envs/pybamm_<XX>_x/. Spawned via:

    <env-python> -m sim._runners.pybamm.runner

with SIM_RUNNER_PROFILE so the runner self-binds to a yaml profile.

═══════════════════════════════════════════════════════════════════════════
ARCHITECTURE — same shape as ComsolMphRunner: abstract base + version
subclasses + registry dispatch. See sim/_runners/comsol/mph_runner.py
for the full extension recipe.
═══════════════════════════════════════════════════════════════════════════

PyBaMM is the simplest runner in the family: there is no JVM, no remote
server, no shell environment to source. op_connect just imports pybamm
into the runner's namespace; op_exec runs snippets with `pybamm`,
`session` (a dict the user can use as scratchpad), and `_result`
in scope.

The version-sensitive hooks exist mostly to future-proof — pybamm 25→26
broke the Battery_DFN parameter set, and 23→24 changed the Solver API
shape. Each is a small override on Mph1Runner-style subclass.
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
from typing import Any, Callable

from sim._runners.base import RunnerError, RunnerLoop


# ─── abstract base ──────────────────────────────────────────────────────────


class PyBaMMRunner(RunnerLoop):
    """Abstract PyBaMM runner. Subclasses set ``variant`` and override hooks."""

    profile_name = "<unset>"
    variant: str = "abstract"

    def __init__(self) -> None:
        super().__init__()
        self._pybamm: Any = None
        self._session_state: dict[str, Any] = {}
        self._session_id: str | None = None
        self._runs: list[dict] = []
        self._sdk_version: str = "?"

    # ── version-sensitive hooks ─────────────────────────────────────────

    def _import_pybamm(self) -> Any:
        """Import the pybamm package. Override only if a future version
        renames the top-level module."""
        import pybamm
        return pybamm

    def _query_solver_version(self, pybamm: Any) -> str:
        return getattr(pybamm, "__version__", "unknown")

    def _build_namespace(self, pybamm: Any, session: dict) -> dict[str, Any]:
        """Construct the exec namespace for snippets. Override to inject
        version-specific helpers (e.g. a 25.x-only convenience constructor).
        """
        return {
            "pybamm": pybamm,
            "session": session,
            "_result": None,
        }

    # ── op_handshake ────────────────────────────────────────────────────

    def op_handshake(self, args: dict) -> dict:
        try:
            self._pybamm = self._import_pybamm()
        except ImportError as e:
            raise RunnerError(
                f"`pybamm` import failed inside profile env: {e}",
                type="SDKImportError",
            ) from e

        self._sdk_version = self._query_solver_version(self._pybamm)

        return {
            "sdk_version": self._sdk_version,
            "solver_version": self._sdk_version,   # pybamm IS the solver
            "profile": self.profile_name,
            "variant": self.variant,
        }

    # ── op_connect / op_disconnect ──────────────────────────────────────

    def op_connect(self, args: dict) -> dict:
        if self._session_id is not None:
            raise RunnerError("session already active")
        # No real "connect" — pybamm is in-process. Just open a session.
        self._session_id = str(uuid.uuid4())
        self._session_state = {}
        return {
            "session_id": self._session_id,
            "mode": "in-process",
            "source": "import",
            "profile": self.profile_name,
            "variant": self.variant,
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

        namespace = self._build_namespace(self._pybamm, self._session_state)

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

        # Snippets that bind names to `session[...]` persist across calls;
        # we don't try to merge top-level locals back into session_state
        # because that pollutes the namespace with `pybamm` etc.

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
                "variant": self.variant,
            }
        if name == "session.summary":
            return {
                "session_id": self._session_id,
                "mode": "in-process",
                "profile": self.profile_name,
                "variant": self.variant,
                "run_count": len(self._runs),
                "connected": self._session_id is not None,
                "session_state_keys": sorted(self._session_state.keys()),
            }
        if name == "last.result":
            if not self._runs:
                return {"has_last_run": False}
            return {"has_last_run": True, **self._runs[-1]}
        raise RunnerError(f"unknown inspect target: {name}", type="UnknownInspect")


# ─── concrete subclasses ────────────────────────────────────────────────────


class PyBaMM24Runner(PyBaMMRunner):
    """PyBaMM 24.x — Battery_DFN / SPMe / SPM stable API."""
    variant = "pybamm_24"


class PyBaMM25Runner(PyBaMMRunner):
    """PyBaMM 25.x — currently identical to 24.x at the runner level.

    If pybamm 25 introduces breaking changes (e.g. parameter set renames),
    override _build_namespace here to inject a compatibility shim.
    """
    variant = "pybamm_25"


# ─── variant registry + dispatch ────────────────────────────────────────────


_RUNNER_REGISTRY: dict[str, Callable[[], PyBaMMRunner]] = {
    "pybamm_24": PyBaMM24Runner,
    "pybamm_25": PyBaMM25Runner,
}


def _select_variant() -> str:
    """Resolution order: SIM_RUNNER_VARIANT → profile.extra → SDK probe → fallback."""
    explicit = os.environ.get("SIM_RUNNER_VARIANT")
    if explicit:
        return explicit

    profile_name = os.environ.get("SIM_RUNNER_PROFILE")
    if profile_name:
        try:
            from sim.compat import find_profile
            found = find_profile(profile_name)
            if found is not None:
                _, profile = found
                extra = getattr(profile, "extra", None) or {}
                if extra.get("runner_variant"):
                    return str(extra["runner_variant"])
        except Exception:
            pass

    try:
        import pybamm as _p
        m = re.match(r"(\d+)\.", getattr(_p, "__version__", ""))
        if m:
            return f"pybamm_{m.group(1)}"
    except Exception:
        pass

    return "pybamm_25"  # newest


def main() -> int:
    profile = os.environ.get("SIM_RUNNER_PROFILE", "pybamm_25_x")
    variant = _select_variant()
    runner_cls = _RUNNER_REGISTRY.get(variant)
    if runner_cls is None:
        sys.stderr.write(
            f"[pybamm_runner] unknown variant {variant!r}, "
            f"falling back to pybamm_25 (registered: {sorted(_RUNNER_REGISTRY)})\n"
        )
        runner_cls = PyBaMM25Runner
    runner = runner_cls()
    runner.profile_name = profile
    return runner.run()


if __name__ == "__main__":
    sys.exit(main())
