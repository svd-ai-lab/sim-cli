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
"""
from __future__ import annotations

import io
import time
import traceback
import uuid
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="sim", version="0.1.0")


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
    session: Any = None
    driver: Any = None
    runs: list[dict] = field(default_factory=list)


_state = SessionState()


# ── Snippet execution ────────────────────────────────────────────────────────

def _execute_snippet(code: str, label: str) -> dict:
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    namespace: dict[str, Any] = {
        "session": _state.session,
        "_result": None,
    }
    if _state.mode == "meshing":
        namespace["meshing"] = _state.session
    else:
        namespace["solver"] = _state.session

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

    run_record = {
        "run_id": str(uuid.uuid4()),
        "session_id": _state.session_id,
        "label": label,
        "code": code,
        "ok": ok,
        "stdout": stdout_buf.getvalue(),
        "stderr": stderr_buf.getvalue(),
        "error": error,
        "result": namespace.get("_result"),
        "elapsed_s": elapsed,
        "started_at": started,
    }
    _state.runs.append(run_record)
    _state.run_count += 1
    return run_record


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/version")
def version():
    from sim import __version__
    return {"version": __version__}


@app.get("/detect/{solver}")
def detect_solver(solver: str):
    """On-demand detection of one named solver on this host.

    Returns the same shape that local `sim check <solver>` produces, so the
    CLI can use the same rendering code for both local and remote detection.

    Per docs/architecture/version-compat.md §5.2, this endpoint runs the
    SAME `driver.detect_installed()` code that the local path runs — it just
    runs it on the host where sim serve is executing.
    """
    from pathlib import Path

    from sim.compat import load_compatibility, safe_detect_installed
    from sim.drivers import get_driver

    driver = get_driver(solver)
    if driver is None:
        raise HTTPException(404, f"unknown solver: {solver}")

    installs = safe_detect_installed(driver)

    # Try to resolve each install against the driver's compatibility.yaml
    driver_dir = Path(__file__).parent / "drivers" / solver
    resolutions: list[dict] = []
    compat_dict: dict | None = None
    try:
        compat = load_compatibility(driver_dir)
        compat_dict = {
            "driver": compat.driver,
            "sdk_package": compat.sdk_package,
            "profiles": [p.to_dict() for p in compat.profiles],
            "deprecated": [d.to_dict() for d in compat.deprecated],
        }
        for inst in installs:
            r = compat.resolve(inst.version)
            resolutions.append({
                "install": inst.to_dict(),
                "resolution": r.to_dict(),
            })
    except FileNotFoundError:
        # Driver hasn't been migrated to the compat schema yet
        for inst in installs:
            resolutions.append({
                "install": inst.to_dict(),
                "resolution": None,
            })

    return {
        "ok": True,
        "data": {
            "solver": solver,
            "installs": [i.to_dict() for i in installs],
            "resolutions": resolutions,
            "compatibility": compat_dict,
        },
    }


@app.post("/connect")
def connect(req: ConnectRequest):
    from sim.drivers import get_driver

    if _state.session is not None:
        raise HTTPException(400, "session already active — POST /disconnect first")

    driver = get_driver(req.solver)
    if driver is None:
        raise HTTPException(400, f"unknown solver: {req.solver}")

    try:
        if req.solver in ("matlab", "comsol"):
            info = driver.launch(ui_mode=req.ui_mode)
            session = driver  # driver holds its own session
        else:
            # Fluent path
            import ansys.fluent.core as pyfluent
            session = pyfluent.launch_fluent(
                mode=req.mode,
                ui_mode=req.ui_mode,
                processor_count=req.processors,
            )
            info = {"ok": True, "session_id": str(uuid.uuid4())}
    except Exception as e:
        raise HTTPException(500, f"failed to launch {req.solver}: {e}")

    _state.session_id = info.get("session_id", str(uuid.uuid4()))
    _state.solver = req.solver
    _state.mode = req.mode
    _state.ui_mode = req.ui_mode
    _state.connected_at = time.time()
    _state.run_count = 0
    _state.session = session
    _state.driver = driver
    _state.runs = []

    return {
        "ok": True,
        "data": {
            "session_id": _state.session_id,
            "solver": req.solver,
            "mode": _state.mode,
            "ui_mode": _state.ui_mode,
            "connected_at": _state.connected_at,
            "run_count": 0,
        },
    }


@app.post("/exec")
def exec_snippet(req: ExecRequest):
    if _state.session is None:
        raise HTTPException(400, "no active session — POST /connect first")

    if _state.solver in ("matlab", "comsol"):
        result = _state.driver.run(req.code, req.label)
        result["session_id"] = _state.session_id
        result["started_at"] = time.time()
        _state.runs.append(result)
        _state.run_count += 1
        return {"ok": result["ok"], "data": result}

    record = _execute_snippet(req.code, req.label)
    return {"ok": record["ok"], "data": record}


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
    if _state.session is None:
        raise HTTPException(400, "no active session")

    if name == "session.summary":
        return {
            "ok": True,
            "data": {
                "session_id": _state.session_id,
                "mode": _state.mode,
                "ui_mode": _state.ui_mode,
                "connected_at": _state.connected_at,
                "run_count": _state.run_count,
                "connected": True,
            },
        }
    elif name == "last.result":
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
    else:
        raise HTTPException(404, f"unknown inspect target: {name}")


@app.get("/ps")
def ps():
    if _state.session is None:
        return {"connected": False}
    return {
        "connected": True,
        "session_id": _state.session_id,
        "solver": _state.solver,
        "mode": _state.mode,
        "ui_mode": _state.ui_mode,
        "connected_at": _state.connected_at,
        "run_count": _state.run_count,
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


@app.post("/disconnect")
def disconnect():
    if _state.session is None:
        raise HTTPException(400, "no active session")

    sid = _state.session_id
    try:
        if _state.solver in ("matlab", "comsol") and _state.driver:
            _state.driver.disconnect()
        else:
            _state.session.exit()
    except Exception:
        pass

    _state.session = None
    _state.session_id = None
    _state.solver = None
    _state.mode = None
    _state.ui_mode = None
    _state.connected_at = None
    _state.run_count = 0
    _state.driver = None
    _state.runs = []

    return {"ok": True, "data": {"session_id": sid, "disconnected": True}}
