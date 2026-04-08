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

import math

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel


def _sanitize_for_json(obj):
    """Recursively replace NaN/+Inf/-Inf floats with None.

    FastAPI's default JSONResponse encoder rejects out-of-range floats,
    which crashes /exec and /inspect when a runner returns numeric results
    that include NaN (e.g. an unsolved COMSOL evaluation). Replacing them
    with None keeps the wire format strict-JSON-compliant without losing
    the surrounding payload.
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
    """JSONResponse subclass that sanitizes NaN/Inf before encoding."""

    def render(self, content) -> bytes:
        return super().render(_sanitize_for_json(content))


app = FastAPI(title="sim", version="0.1.0", default_response_class=_NaNSafeJSONResponse)


# ── Request models ───────────────────────────────────────────────────────────

class ConnectRequest(BaseModel):
    solver: str = "fluent"
    mode: str = "meshing"
    ui_mode: str = "gui"
    processors: int = 2
    profile: str | None = None         # explicit profile name override
    inline: bool = False               # legacy in-process path (tests / debug)


class EnvInstallRequest(BaseModel):
    profile: str
    upgrade: bool = False


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
    session: Any = None       # in-process Fluent session (legacy inline path)
    driver: Any = None
    runs: list[dict] = field(default_factory=list)
    # New (M1): when the session was launched via a profile env runner,
    # this holds the live RunnerClient and the profile metadata.
    runner: Any = None        # sim._runner_client.RunnerClient | None
    profile: str | None = None
    env_path: str | None = None


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


def _have_active_session() -> bool:
    return _state.runner is not None or _state.session is not None


def _driver_has_compat(solver: str) -> bool:
    """True if drivers/<solver>/compatibility.yaml exists."""
    from pathlib import Path
    return (Path(__file__).parent / "drivers" / solver / "compatibility.yaml").is_file()


def _sdk_package_for_solver(solver: str) -> str | None:
    """Look up the SDK package name from a driver's compatibility.yaml.

    Returns None for SDK-less drivers (e.g. openfoam) or drivers without
    a compatibility.yaml.
    """
    from pathlib import Path
    from sim.compat import load_compatibility
    try:
        compat = load_compatibility(Path(__file__).parent / "drivers" / solver)
    except (FileNotFoundError, ValueError):
        return None
    return compat.sdk_package


@app.post("/connect")
def connect(req: ConnectRequest):
    """Open a solver session.

    Default path (M1): detect → resolve profile → spawn runner subprocess
    in the matching profile env → forward op=connect to it. Used for fluent.

    Inline path: when ``inline: true`` is sent, or for solvers that have
    not been migrated to the runner architecture (matlab, comsol), the
    server runs the solver in its own process. This path is the legacy
    one and is kept for backward compatibility.
    """
    from sim.drivers import get_driver

    if _have_active_session():
        raise HTTPException(400, "session already active — POST /disconnect first")

    driver = get_driver(req.solver)
    if driver is None:
        raise HTTPException(400, f"unknown solver: {req.solver}")

    # ── runner path: any driver that ships a compatibility.yaml ─────────
    # The runner path is now the default for every solver that has been
    # migrated to the M1 architecture. Drivers without a compatibility.yaml
    # (matlab, comsol, …) fall through to the legacy inline path below.
    if not req.inline and _driver_has_compat(req.solver):
        return _connect_via_runner(driver, req)

    # ── legacy inline path ──────────────────────────────────────────────
    try:
        if req.solver in ("matlab", "comsol"):
            info = driver.launch(ui_mode=req.ui_mode)
            session = driver
        elif req.solver == "fluent":
            import ansys.fluent.core as pyfluent
            session = pyfluent.launch_fluent(
                mode=req.mode,
                ui_mode=req.ui_mode,
                processor_count=req.processors,
            )
            info = {"ok": True, "session_id": str(uuid.uuid4())}
        else:
            raise HTTPException(400, f"no inline path for solver: {req.solver}")
    except HTTPException:
        raise
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
            "transport": "inline",
        },
    }


def _connect_via_runner(driver, req: ConnectRequest):
    """Detect → resolve profile → spawn runner → handshake → op=connect."""
    from sim import env_manager
    from sim._runner_client import (
        RunnerCallError,
        RunnerClientError,
        spawn_runner_for_profile,
    )
    from sim.compat import find_profile, resolve_profile_for_driver

    # 1) Resolve which profile to use
    profile_name = req.profile
    install_info: dict | None = None
    if profile_name is None:
        resolved = resolve_profile_for_driver(driver)
        if resolved is None:
            raise HTTPException(
                404,
                f"no {req.solver} installation detected on the host running sim serve. "
                f"Run `sim check {req.solver}` here to diagnose.",
            )
        profile, install_info = resolved
        profile_name = profile.name
    else:
        found = find_profile(profile_name)
        if not found:
            raise HTTPException(400, f"unknown profile: {profile_name}")

    # 2) Ensure the profile env is bootstrapped
    state = env_manager.env_state(profile_name)
    if not state:
        raise HTTPException(
            409,
            f"profile env not bootstrapped: {profile_name}. "
            f"Run `sim env install {profile_name}` (locally or via --host) first.",
        )

    # 3) Spawn runner subprocess + handshake
    try:
        client = spawn_runner_for_profile(profile_name)
    except RunnerClientError as e:
        raise HTTPException(500, f"failed to spawn runner: {e}")

    # 4) Forward op=connect to the runner
    try:
        connect_result = client.call(
            "connect",
            {
                "mode": req.mode,
                "ui_mode": req.ui_mode,
                "processors": req.processors,
            },
            timeout=None,
        )
    except RunnerCallError as e:
        client.stop()
        raise HTTPException(
            500,
            f"runner op=connect failed ({e.error_type}): {e.error_message}",
        )
    except RunnerClientError as e:
        client.stop()
        raise HTTPException(500, f"runner IPC error during connect: {e}")

    _state.runner = client
    _state.session_id = connect_result.get("session_id") or str(uuid.uuid4())
    _state.solver = req.solver
    _state.mode = req.mode
    _state.ui_mode = req.ui_mode
    _state.connected_at = time.time()
    _state.run_count = 0
    _state.driver = driver
    _state.runs = []
    _state.profile = profile_name
    _state.env_path = state.get("env_path")

    return {
        "ok": True,
        "data": {
            "session_id": _state.session_id,
            "solver": req.solver,
            "mode": _state.mode,
            "ui_mode": _state.ui_mode,
            "connected_at": _state.connected_at,
            "run_count": 0,
            "transport": "runner",
            "profile": profile_name,
            "env_path": _state.env_path,
            "sdk": (
                {
                    "name": _sdk_package_for_solver(req.solver),
                    "version": client.handshake.sdk_version if client.handshake else "?",
                }
                if _sdk_package_for_solver(req.solver) is not None
                else None
            ),
            "solver_detected": {
                "name": req.solver,
                "version": client.handshake.solver_version if client.handshake else "?",
            },
            "variant": connect_result.get("variant"),
            "install_origin": install_info,
        },
    }


@app.post("/env/install")
def env_install_endpoint(req: EnvInstallRequest):
    """Bootstrap a profile env on the server's host.

    Required so that ``sim --host <ip> env install <profile>`` lands the
    SDK on the same machine as the solver, not on the user's laptop.
    """
    from sim import env_manager

    try:
        state = env_manager.install(req.profile, upgrade=req.upgrade, quiet=True)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    return {"ok": True, "data": state}


@app.get("/env/list")
def env_list_endpoint():
    from sim import env_manager
    return {"ok": True, "data": {"installed": env_manager.list_envs()}}


@app.post("/exec")
def exec_snippet(req: ExecRequest):
    if not _have_active_session():
        raise HTTPException(400, "no active session — POST /connect first")

    # Runner path (M1 default)
    if _state.runner is not None:
        from sim._runner_client import RunnerCallError, RunnerClientError
        try:
            record = _state.runner.call(
                "exec",
                {"code": req.code, "label": req.label},
                timeout=None,
            )
        except RunnerCallError as e:
            return {
                "ok": False,
                "data": {
                    "ok": False,
                    "label": req.label,
                    "error": f"{e.error_type}: {e.error_message}",
                    "traceback": e.traceback,
                },
            }
        except RunnerClientError as e:
            raise HTTPException(500, f"runner IPC error during exec: {e}")

        record["started_at"] = time.time()
        _state.runs.append(record)
        _state.run_count += 1
        return {"ok": record.get("ok", False), "data": record}

    # Legacy inline paths
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
    if not _have_active_session():
        raise HTTPException(400, "no active session")

    # session.versions is special: always available, comes from the runner
    # handshake or a degraded summary for inline sessions.
    if name == "session.versions":
        if _state.runner is not None and _state.runner.handshake is not None:
            hs = _state.runner.handshake
            sdk_pkg = _sdk_package_for_solver(_state.solver or "")
            return {
                "ok": True,
                "data": {
                    "sdk": (
                        {"name": sdk_pkg, "version": hs.sdk_version}
                        if sdk_pkg is not None
                        else None
                    ),
                    "solver": {
                        "name": _state.solver,
                        "version": hs.solver_version,
                    },
                    "profile": hs.profile,
                    "skill_revision": _profile_skill_revision(hs.profile),
                    "env_path": _state.env_path,
                },
            }
        # Inline session — no runner, no profile, just report what we know
        return {
            "ok": True,
            "data": {
                "sdk": None,
                "solver": {"name": _state.solver, "version": None},
                "profile": None,
                "skill_revision": None,
                "env_path": None,
            },
        }

    # Forward to runner if present
    if _state.runner is not None:
        from sim._runner_client import RunnerCallError, RunnerClientError
        try:
            data = _state.runner.call("inspect", {"name": name})
        except RunnerCallError as e:
            raise HTTPException(404, f"{e.error_type}: {e.error_message}")
        except RunnerClientError as e:
            raise HTTPException(500, f"runner IPC error during inspect: {e}")
        return {"ok": True, "data": data}

    # Legacy inline path
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


def _profile_skill_revision(profile_name: str) -> str | None:
    """Look up a profile's skill_revision via the global compat catalogue."""
    from sim.compat import find_profile
    found = find_profile(profile_name)
    if not found:
        return None
    _, profile = found
    return profile.skill_revision


@app.get("/ps")
def ps():
    if not _have_active_session():
        return {"connected": False}
    out = {
        "connected": True,
        "session_id": _state.session_id,
        "solver": _state.solver,
        "mode": _state.mode,
        "ui_mode": _state.ui_mode,
        "connected_at": _state.connected_at,
        "run_count": _state.run_count,
        "transport": "runner" if _state.runner is not None else "inline",
    }
    if _state.runner is not None:
        out["profile"] = _state.profile
        out["env_path"] = _state.env_path
    return out


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
    if not _have_active_session():
        raise HTTPException(400, "no active session")

    sid = _state.session_id

    # Runner path: ask runner to op=disconnect, then op=shutdown
    if _state.runner is not None:
        from sim._runner_client import RunnerCallError, RunnerClientError
        try:
            _state.runner.call("disconnect", {})
        except (RunnerCallError, RunnerClientError):
            pass  # tear down even if disconnect rpc fails
        try:
            _state.runner.stop()
        except Exception:
            pass
        _state.runner = None

    # Legacy inline path
    elif _state.solver in ("matlab", "comsol") and _state.driver:
        try:
            _state.driver.disconnect()
        except Exception:
            pass
    elif _state.session is not None:
        try:
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
    _state.profile = None
    _state.env_path = None

    return {"ok": True, "data": {"session_id": sid, "disconnected": True}}
