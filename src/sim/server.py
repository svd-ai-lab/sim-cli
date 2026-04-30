"""sim serve — HTTP server that holds one or more live simulation sessions.

Like `ollama serve`: start once, then use `sim connect/exec/inspect/disconnect`.

    sim serve                          # local (127.0.0.1:7600)
    sim serve --host 0.0.0.0           # expose on network (Tailscale)
    sim serve --host 0.0.0.0 --port 8000

Multi-session model (issue #26):

Each `/connect` opens an independent session with a fresh `session_id`.
Subsequent per-session calls route by the `X-Sim-Session` header. When
only one session is live, the header is optional — the server picks the
sole session as default. With two or more sessions live and no header,
per-session endpoints return 400. See
`docs/architecture/multi-session-and-config.md` for the full contract.

Endpoints:
    POST /connect     {solver, mode, ui_mode, processors, ...} → header-less
    POST /exec        {code, label}                           → header-routed
    POST /run         {script, solver}                        → header-less (one-shot)
    GET  /inspect/<name>                                      → header-routed
    GET  /ps                                                  → header-less (lists all)
    GET  /screenshot                                          → header-less (global)
    POST /disconnect                                          → header-routed
    POST /shutdown                                            → header-less (tears down all)
"""
from __future__ import annotations

import io
import math
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


def _sanitize_for_json(obj):
    """Recursively replace NaN/+Inf/-Inf floats with None.

    FastAPI's default JSONResponse encoder rejects out-of-range floats,
    which crashes /exec and /inspect when a driver returns numeric
    results that include NaN (e.g. an unsolved COMSOL evaluation).
    Replacing them with None keeps the wire format strict-JSON-compliant
    without losing the surrounding payload.
    """
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(v) for v in obj]
    return obj


class _NaNSafeJSONResponse(JSONResponse):
    def render(self, content) -> bytes:
        return super().render(_sanitize_for_json(content))


app = FastAPI(title="sim", version="0.2.0", default_response_class=_NaNSafeJSONResponse)


# ── Request models ───────────────────────────────────────────────────────────

class ConnectRequest(BaseModel):
    solver: str = "fluent"
    mode: str = "meshing"
    ui_mode: str = "gui"
    processors: int = 2
    workspace: str | None = None
    driver_options: dict[str, Any] = Field(default_factory=dict)


def _connect_reserved_driver_option_keys() -> set[str]:
    """Return connect request fields that cannot be overridden by driver options."""
    fields = getattr(ConnectRequest, "model_fields", None)
    if fields is None:
        fields = getattr(ConnectRequest, "__fields__", {})
    return set(fields) - {"driver_options"}


class ExecRequest(BaseModel):
    code: str
    label: str = "snippet"


class RunRequest(BaseModel):
    script: str
    solver: str


# ── Session state ────────────────────────────────────────────────────────────

@dataclass
class SessionState:
    session_id: str
    solver: str
    mode: str | None = None
    ui_mode: str | None = None
    processors: int = 1
    workspace: str | None = None
    driver_options: dict = field(default_factory=dict)
    launch_options: dict = field(default_factory=dict)
    connected_at: float | None = None
    run_count: int = 0
    driver: Any = None
    runs: list[dict] = field(default_factory=list)
    profile: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


# Module-level multi-session registry. Two independent locks: `_sessions_lock`
# for dict mutations (add/remove/iter), per-session `.lock` for body-of-work
# serialization (exec calls on the same driver).
_sessions: dict[str, SessionState] = {}
_sessions_lock = threading.Lock()


# ── Session selector ─────────────────────────────────────────────────────────


def _select_session(header_val: str | None) -> SessionState:
    """Resolve the target session from header + default-picking rules.

    Rules (design note §6):
      1. If header is set, use it. 404 on unknown id.
      2. Else if exactly one session live, pick it.
      3. Else 400 with a helpful message.
    """
    with _sessions_lock:
        if header_val:
            s = _sessions.get(header_val)
            if s is None:
                raise HTTPException(404, f"unknown session_id: {header_val}")
            return s
        if len(_sessions) == 1:
            return next(iter(_sessions.values()))
        if not _sessions:
            raise HTTPException(400, "no active sessions — POST /connect first")
        raise HTTPException(
            400,
            f"{len(_sessions)} sessions live; set X-Sim-Session header or use `sim --session <id>`",
        )


def _register_session(state: SessionState) -> None:
    with _sessions_lock:
        _sessions[state.session_id] = state


def _drop_session(session_id: str) -> SessionState | None:
    with _sessions_lock:
        return _sessions.pop(session_id, None)


def _list_sessions() -> list[SessionState]:
    with _sessions_lock:
        return list(_sessions.values())


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/version")
def version():
    from sim import __version__
    return {"version": __version__}


@app.get("/detect/{solver}")
def detect_solver(solver: str):
    """On-demand detection of one named solver on this host.

    Returns the same shape that local `sim check <solver>` produces, so
    the CLI can use the same rendering code for both local and remote
    detection.
    """
    from sim.compat import load_compatibility_by_name, safe_detect_installed
    from sim.drivers import get_driver

    try:
        driver = get_driver(solver)
    except Exception as e:  # noqa: BLE001 — surface lazy-import failures distinctly
        raise HTTPException(500, f"driver '{solver}' failed to load: {type(e).__name__}: {e}")
    if driver is None:
        raise HTTPException(404, f"unknown solver: {solver}")

    installs = safe_detect_installed(driver)

    resolutions: list[dict] = []
    compat_dict: dict | None = None
    compat = load_compatibility_by_name(solver)
    if compat is not None:
        compat_dict = {
            "driver": compat.driver,
            "sdk_package": compat.sdk_package,
            "profiles": [p.to_dict() for p in compat.profiles],
        }
        for inst in installs:
            profile = compat.resolve(inst.version)
            resolutions.append({
                "install": inst.to_dict(),
                "profile": profile.to_dict() if profile else None,
            })
    else:
        for inst in installs:
            resolutions.append({"install": inst.to_dict(), "profile": None})

    return {
        "ok": True,
        "data": {
            "solver": solver,
            "installs": [i.to_dict() for i in installs],
            "resolutions": resolutions,
            "compatibility": compat_dict,
        },
    }


def _resolve_profile(driver, solver: str):
    """Best-effort lookup of which compat.yaml profile applies to the
    detected install. Returns the Profile, or None on miss / failure.
    Never raises.
    """
    from sim.compat import load_compatibility_by_name, safe_detect_installed

    installs = safe_detect_installed(driver)
    if not installs:
        return None
    compat = load_compatibility_by_name(solver)
    if compat is None:
        return None
    for inst in sorted(installs, key=lambda i: i.version, reverse=True):
        profile = compat.resolve(inst.version)
        if profile is not None:
            return profile
    return None


@app.post("/connect")
def connect(req: ConnectRequest):
    """Open a solver session. Multi-session: never conflicts with an existing one.

    sim-cli runs every driver in its own process — the same Python that
    runs sim serve also imports the SDK directly. There is no subprocess
    isolation and no per-profile env management. The resolved profile is
    attached to the response as a label so the agent (and skills layer)
    can know which compat.yaml entry is in effect.
    """
    from sim.drivers import get_driver

    try:
        driver = get_driver(req.solver)
    except Exception as e:  # noqa: BLE001 — surface lazy-import failures distinctly
        raise HTTPException(500, f"driver '{req.solver}' failed to load: {type(e).__name__}: {e}")
    if driver is None:
        raise HTTPException(400, f"unknown solver: {req.solver}")

    if not getattr(driver, "supports_session", False):
        raise HTTPException(
            400,
            f"{req.solver} does not support persistent sessions. "
            "Use POST /run for one-shot execution.",
        )

    # Single-driver-instance limitation: the current `DriverProtocol`
    # classes are module-level singletons, so holding two concurrent
    # sessions on the *same* driver class would alias driver internal
    # state. Multi-solver parallelism (fluent + mechanical) is the
    # supported case; two fluent sessions is not yet.
    with _sessions_lock:
        for s in _sessions.values():
            if s.solver == req.solver:
                raise HTTPException(
                    400,
                    f"a {req.solver} session is already live (id={s.session_id}); "
                    "two concurrent sessions on the same driver aren't supported yet",
                )

    reserved_seen = _connect_reserved_driver_option_keys() & set(req.driver_options)
    if reserved_seen:
        names = ", ".join(sorted(reserved_seen))
        raise HTTPException(
            400,
            f"driver_options may not override reserved connect keys: {names}",
        )

    launch_kwargs: dict = {
        "mode": req.mode,
        "ui_mode": req.ui_mode,
        "processors": req.processors,
        **req.driver_options,
    }
    if req.workspace is not None:
        launch_kwargs["workspace"] = req.workspace
        launch_kwargs.setdefault("cwd", req.workspace)
    try:
        info = driver.launch(**launch_kwargs)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"failed to launch {req.solver}: {e}")

    from sim.compat import skills_block_for_profile
    profile = _resolve_profile(driver, req.solver)

    sid = info.get("session_id") or f"s-{uuid.uuid4().hex[:8]}"
    state = SessionState(
        session_id=sid,
        solver=req.solver,
        mode=req.mode,
        ui_mode=req.ui_mode,
        processors=req.processors,
        workspace=req.workspace,
        driver_options=req.driver_options,
        launch_options=info.get("launch_options") or {},
        connected_at=time.time(),
        run_count=0,
        driver=driver,
        runs=[],
        profile=profile.name if profile else None,
    )
    _register_session(state)

    # Tool advertisement (Phase 3). Tells the agent which cross-driver
    # actuation objects are live in the exec namespace for this session,
    # plus where to find the tool's skill document. ``gui`` is the first
    # entry — present whenever the driver constructed a ``GuiController``
    # at launch (i.e. ui_mode=gui/desktop on a GUI-capable driver).
    tools: list[str] = []
    tool_refs: dict[str, str] = {}
    if getattr(driver, "_gui", None) is not None:
        tools.append("gui")
        tool_refs["gui"] = "sim-skills/sim-cli/gui/SKILL.md"

    return {
        "ok": True,
        "data": {
            "session_id": state.session_id,
            "solver": req.solver,
            "mode": state.mode,
            "ui_mode": state.ui_mode,
            "workspace": state.workspace,
            "driver_options": state.driver_options,
            "launch_options": state.launch_options,
            "connected_at": state.connected_at,
            "run_count": 0,
            "profile": state.profile,
            "skills": skills_block_for_profile(req.solver, profile),
            "tools": tools,
            "tool_refs": tool_refs,
        },
    }


@app.post("/exec")
def exec_snippet(
    req: ExecRequest,
    x_sim_session: str | None = Header(default=None, alias="X-Sim-Session"),
):
    state = _select_session(x_sim_session)
    # Serialize calls on the same session; different sessions run in parallel.
    with state.lock:
        result = state.driver.run(req.code, req.label)
        result.setdefault("session_id", state.session_id)
        result.setdefault("started_at", time.time())
        state.runs.append(result)
        state.run_count += 1
    return {"ok": result.get("ok", True), "data": result}


@app.post("/run")
def run_script(req: RunRequest):
    """One-shot script execution — no session required."""
    from pathlib import Path

    from sim.drivers import get_driver
    from sim.runner import execute_script

    script_path = Path(req.script)
    if not script_path.is_file():
        raise HTTPException(400, f"script not found: {req.script}")

    try:
        driver = get_driver(req.solver)
    except Exception as e:  # noqa: BLE001 — surface lazy-import failures distinctly
        raise HTTPException(500, f"driver '{req.solver}' failed to load: {type(e).__name__}: {e}")
    if driver is None:
        raise HTTPException(400, f"unknown solver: {req.solver}")

    result = execute_script(script_path, solver=req.solver, driver=driver)
    parsed = driver.parse_output(result.stdout)

    return {
        "ok": result.exit_code == 0,
        "data": {
            **result.to_dict(),
            "parsed": parsed,
        },
    }


@app.get("/inspect/{name}")
def inspect(
    name: str,
    x_sim_session: str | None = Header(default=None, alias="X-Sim-Session"),
):
    state = _select_session(x_sim_session)

    if name == "session.summary":
        return {
            "ok": True,
            "data": {
                "session_id": state.session_id,
                "solver": state.solver,
                "mode": state.mode,
                "ui_mode": state.ui_mode,
                "workspace": state.workspace,
                "driver_options": state.driver_options,
                "launch_options": state.launch_options,
                "connected_at": state.connected_at,
                "run_count": state.run_count,
                "profile": state.profile,
                "connected": True,
            },
        }
    if name == "last.result":
        if not state.runs:
            return {"ok": True, "data": {"has_last_run": False}}
        last = state.runs[-1]
        return {
            "ok": True,
            "data": {
                "has_last_run": True,
                **{k: v for k, v in last.items() if k != "code"},
            },
        }
    # Fallback: ask the active driver to handle driver-specific inspect targets
    # (e.g. ls_dyna's deck.summary, mechanical.project_directory)
    driver = state.driver
    if driver is not None and hasattr(driver, "query"):
        try:
            result = driver.query(name)
        except Exception as exc:
            raise HTTPException(500, f"driver query failed: {exc}") from exc
        if isinstance(result, dict):
            if result.get("ok") is False:
                raise HTTPException(404, result.get("error", f"unknown inspect target: {name}"))
            return {"ok": True, "data": result}
    raise HTTPException(404, f"unknown inspect target: {name}")


@app.get("/ps")
def ps():
    """List all active sessions (new multi-session shape).

    With no sessions: `{sessions: [], default_session: null}`.
    With one or more: `{sessions: [...], default_session: <id>}`.
    """
    sessions = _list_sessions()
    rows = [
        {
            "session_id": s.session_id,
            "solver": s.solver,
            "mode": s.mode,
            "ui_mode": s.ui_mode,
            "processors": s.processors,
            "workspace": s.workspace,
            "driver_options": s.driver_options,
            "launch_options": s.launch_options,
            "connected_at": s.connected_at,
            "run_count": s.run_count,
            "profile": s.profile,
        }
        for s in sessions
    ]
    default = sessions[0].session_id if len(sessions) == 1 else None
    return {
        "sessions": rows,
        "default_session": default,
        "server_pid": os.getpid(),
    }


@app.get("/screenshot")
def screenshot():
    """Capture the server's desktop and return as PNG.

    Not session-scoped — there's one physical desktop per server host.
    """
    import base64

    try:
        from PIL import ImageGrab
    except ImportError:
        raise HTTPException(500, "Pillow is not installed on the server")

    img = ImageGrab.grab()
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    return {
        "ok": True,
        "data": {
            "format": "png",
            "width": img.width,
            "height": img.height,
            "base64": b64,
        },
    }


def _teardown_session(session_id: str) -> str | None:
    """Best-effort: tear down one session by id. Returns the id torn down, or None."""
    state = _drop_session(session_id)
    if state is None:
        return None
    if state.driver is not None:
        try:
            state.driver.disconnect()
        except Exception:
            pass
    return state.session_id


def _teardown_all() -> list[str]:
    """Tear down every session. Returns the ids that were torn down."""
    with _sessions_lock:
        ids = list(_sessions.keys())
    return [sid for sid in (_teardown_session(i) for i in ids) if sid]


@app.post("/disconnect")
def disconnect(
    x_sim_session: str | None = Header(default=None, alias="X-Sim-Session"),
):
    state = _select_session(x_sim_session)
    sid = _teardown_session(state.session_id)
    return {"ok": True, "data": {"session_id": sid, "disconnected": True}}


@app.post("/shutdown")
def shutdown(request: Request, background_tasks: BackgroundTasks):
    """Stop the sim-server process cleanly.

    Tears down ALL active sessions, then schedules the process to exit
    once the response has been flushed. Localhost-only — when sim serve
    is exposed via --host 0.0.0.0 we don't want a LAN peer to be able
    to take it down.
    """
    client_host = request.client.host if request.client else None
    if client_host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(
            403,
            f"/shutdown is localhost-only (request from {client_host})",
        )

    torn_down = _teardown_all()

    def _exit_after_flush() -> None:
        import time as _t
        _t.sleep(0.1)
        os._exit(0)

    background_tasks.add_task(_exit_after_flush)
    return {
        "ok": True,
        "data": {
            "shutting_down": True,
            "disconnected_sessions": torn_down,
        },
    }
