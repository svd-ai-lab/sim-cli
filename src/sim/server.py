"""sim serve — HTTP server that holds a live simulation session.

Like `ollama serve`: start once, then use `sim connect/exec/inspect/disconnect`.

    sim serve                          # local (127.0.0.1:7600)
    sim serve --host 0.0.0.0           # expose on network (Tailscale)
    sim serve --host 0.0.0.0 --port 8000

Endpoints:
    POST /connect     {solver, mode, ui_mode, processors}
    POST /exec        {code, label}
    POST /run         {script, solver}  — one-shot, no session needed
    GET  /inspect/<name>
    GET  /ps
    POST /disconnect
    POST /shutdown
"""
from __future__ import annotations

import io
import math
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel


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


app = FastAPI(title="sim", version="0.1.0", default_response_class=_NaNSafeJSONResponse)


# ── Request models ───────────────────────────────────────────────────────────

class ConnectRequest(BaseModel):
    solver: str = "fluent"
    mode: str = "meshing"
    ui_mode: str = "gui"
    processors: int = 2


class ExecRequest(BaseModel):
    code: str
    label: str = "snippet"


class RunRequest(BaseModel):
    script: str
    solver: str


# ── Session state ────────────────────────────────────────────────────────────

@dataclass
class SessionState:
    session_id: str | None = None
    solver: str | None = None
    mode: str | None = None
    ui_mode: str | None = None
    connected_at: float | None = None
    run_count: int = 0
    driver: Any = None
    runs: list[dict] = field(default_factory=list)
    profile: str | None = None       # resolved profile name (label only)


_state = SessionState()


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
    from pathlib import Path

    from sim.compat import load_compatibility, safe_detect_installed
    from sim.drivers import get_driver

    driver = get_driver(solver)
    if driver is None:
        raise HTTPException(404, f"unknown solver: {solver}")

    installs = safe_detect_installed(driver)

    driver_dir = Path(__file__).parent / "drivers" / solver
    resolutions: list[dict] = []
    compat_dict: dict | None = None
    try:
        compat = load_compatibility(driver_dir)
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
    except FileNotFoundError:
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


def _have_active_session() -> bool:
    return _state.driver is not None and _state.session_id is not None


def _resolve_profile(driver, solver: str):
    """Best-effort lookup of which compat.yaml profile applies to the
    detected install. Returns the Profile, or None on miss / failure.
    Never raises.
    """
    from pathlib import Path
    from sim.compat import load_compatibility, safe_detect_installed

    installs = safe_detect_installed(driver)
    if not installs:
        return None
    try:
        compat = load_compatibility(Path(__file__).parent / "drivers" / solver)
    except (FileNotFoundError, ValueError):
        return None
    for inst in sorted(installs, key=lambda i: i.version, reverse=True):
        profile = compat.resolve(inst.version)
        if profile is not None:
            return profile
    return None


@app.post("/connect")
def connect(req: ConnectRequest):
    """Open a solver session.

    sim-cli runs every driver in its own process — the same Python that
    runs sim serve also imports the SDK directly. There is no subprocess
    isolation and no per-profile env management. The resolved profile is
    attached to the response as a label so the agent (and skills layer)
    can know which compat.yaml entry is in effect.
    """
    from sim.drivers import get_driver

    if _have_active_session():
        raise HTTPException(400, "session already active — POST /disconnect first")

    driver = get_driver(req.solver)
    if driver is None:
        raise HTTPException(400, f"unknown solver: {req.solver}")

    if not getattr(driver, "supports_session", False):
        raise HTTPException(
            400,
            f"{req.solver} does not support persistent sessions. "
            "Use POST /run for one-shot execution.",
        )

    try:
        info = driver.launch(
            mode=req.mode,
            ui_mode=req.ui_mode,
            processors=req.processors,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"failed to launch {req.solver}: {e}")

    from sim.compat import skills_block_for_profile
    profile = _resolve_profile(driver, req.solver)

    _state.session_id = info.get("session_id", str(uuid.uuid4()))
    _state.solver = req.solver
    _state.mode = req.mode
    _state.ui_mode = req.ui_mode
    _state.connected_at = time.time()
    _state.run_count = 0
    _state.driver = driver
    _state.runs = []
    _state.profile = profile.name if profile else None

    return {
        "ok": True,
        "data": {
            "session_id": _state.session_id,
            "solver": req.solver,
            "mode": _state.mode,
            "ui_mode": _state.ui_mode,
            "connected_at": _state.connected_at,
            "run_count": 0,
            "profile": _state.profile,
            "skills": skills_block_for_profile(req.solver, profile),
        },
    }


@app.post("/exec")
def exec_snippet(req: ExecRequest):
    if not _have_active_session():
        raise HTTPException(400, "no active session — POST /connect first")

    result = _state.driver.run(req.code, req.label)
    result.setdefault("session_id", _state.session_id)
    result.setdefault("started_at", time.time())
    _state.runs.append(result)
    _state.run_count += 1
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

    driver = get_driver(req.solver)
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
def inspect(name: str):
    if not _have_active_session():
        raise HTTPException(400, "no active session")

    if name == "session.summary":
        return {
            "ok": True,
            "data": {
                "session_id": _state.session_id,
                "solver": _state.solver,
                "mode": _state.mode,
                "ui_mode": _state.ui_mode,
                "connected_at": _state.connected_at,
                "run_count": _state.run_count,
                "profile": _state.profile,
                "connected": True,
            },
        }
    if name == "last.result":
        if not _state.runs:
            return {"ok": True, "data": {"has_last_run": False}}
        last = _state.runs[-1]
        return {
            "ok": True,
            "data": {
                "has_last_run": True,
                **{k: v for k, v in last.items() if k != "code"},
            },
        }
    raise HTTPException(404, f"unknown inspect target: {name}")


@app.get("/ps")
def ps():
    if not _have_active_session():
        return {"connected": False}
    return {
        "connected": True,
        "session_id": _state.session_id,
        "solver": _state.solver,
        "mode": _state.mode,
        "ui_mode": _state.ui_mode,
        "connected_at": _state.connected_at,
        "run_count": _state.run_count,
        "profile": _state.profile,
    }


@app.get("/screenshot")
def screenshot():
    """Capture the server's desktop and return as PNG."""
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


def _teardown_active_session() -> str | None:
    """Best-effort: tear down whatever session is currently held.

    Reused by /disconnect and /shutdown. Returns the session id that was
    torn down, or None if there was no active session.
    """
    if not _have_active_session():
        return None

    sid = _state.session_id

    if _state.driver is not None:
        try:
            _state.driver.disconnect()
        except Exception:
            pass

    _state.session_id = None
    _state.solver = None
    _state.mode = None
    _state.ui_mode = None
    _state.connected_at = None
    _state.run_count = 0
    _state.driver = None
    _state.runs = []
    _state.profile = None
    return sid


@app.post("/disconnect")
def disconnect():
    if not _have_active_session():
        raise HTTPException(400, "no active session")
    sid = _teardown_active_session()
    return {"ok": True, "data": {"session_id": sid, "disconnected": True}}


@app.post("/shutdown")
def shutdown(request: Request, background_tasks: BackgroundTasks):
    """Stop the sim-server process cleanly.

    Disconnects any active session, then schedules the process to exit
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

    sid = _teardown_active_session()

    def _exit_after_flush() -> None:
        import time as _t
        _t.sleep(0.1)
        os._exit(0)

    background_tasks.add_task(_exit_after_flush)
    return {
        "ok": True,
        "data": {
            "shutting_down": True,
            "disconnected_session": sid,
        },
    }
