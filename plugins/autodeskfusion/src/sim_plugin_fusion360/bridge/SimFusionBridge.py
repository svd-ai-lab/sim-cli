from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import threading
import time
import traceback

import adsk.core
import adsk.fusion


EVENT_ID = "sim.fusion360.bridge.command"
SESSION_ENV = "SIM_FUSION360_SESSION_DIR"

_app = None
_handlers = []
_stop = threading.Event()
_watcher = None
_seen = set()


def _session_dir() -> Path:
    configured = os.environ.get(SESSION_ENV)
    if configured:
        return Path(configured)
    return Path.home() / ".sim" / "fusion360"


def _queue_dir() -> Path:
    return _session_dir() / "queue"


def _status_path() -> Path:
    return _session_dir() / "bridge_status.json"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_status(status: str = "running") -> None:
    doc = _app.activeDocument.name if _app and _app.activeDocument else None
    _write_json(
        _status_path(),
        {
            "ok": True,
            "bridge": "SimFusionBridge",
            "status": status,
            "event_id": EVENT_ID,
            "document_name": doc,
            "heartbeat": time.time(),
        },
    )


def _watch_loop() -> None:
    _queue_dir().mkdir(parents=True, exist_ok=True)
    while not _stop.is_set():
        try:
            _write_status("running")
            for command_path in sorted(_queue_dir().glob("*.json")):
                key = str(command_path)
                if key in _seen:
                    continue
                try:
                    payload = command_path.read_text(encoding="utf-8")
                    _seen.add(key)
                    _app.fireCustomEvent(EVENT_ID, payload)
                except Exception:
                    _seen.discard(key)
        except Exception:
            pass
        _stop.wait(0.5)


class _CommandHandler(adsk.core.CustomEventHandler):
    def notify(self, event_args: adsk.core.CustomEventArgs) -> None:
        try:
            command = json.loads(event_args.additionalInfo)
            _execute(command)
        except Exception:
            # Last resort: the command may be malformed and not include a result path.
            pass


def _execute(command: dict) -> None:
    result_path = Path(command["result"])
    started = time.time()
    stdout = io.StringIO()
    script_payload = None
    ok = True
    error = None

    try:
        for key, value in command.get("env", {}).items():
            os.environ[str(key)] = str(value)

        app = adsk.core.Application.get()
        design = adsk.fusion.Design.cast(app.activeProduct)
        namespace = {
            "__name__": "__sim_fusion360_bridge__",
            "adsk": adsk,
            "app": app,
            "design": design,
            "root": design.rootComponent if design else None,
        }

        with contextlib.redirect_stdout(stdout):
            if command.get("kind") == "script_file":
                script_path = Path(command["script"])
                code = script_path.read_text(encoding="utf-8")
                exec(compile(code, str(script_path), "exec"), namespace)
                if callable(namespace.get("run")):
                    namespace["run"]({})
            elif command.get("kind") == "code":
                exec(command["code"], namespace)
            else:
                raise ValueError(f"Unsupported bridge command kind: {command.get('kind')}")

        if result_path.exists():
            try:
                script_payload = json.loads(result_path.read_text(encoding="utf-8"))
                ok = bool(script_payload.get("ok", True))
            except Exception:
                script_payload = None
    except Exception:
        ok = False
        error = traceback.format_exc()

    payload = script_payload if isinstance(script_payload, dict) else {"ok": ok}
    payload.update({
        "ok": ok,
        "bridge": "SimFusionBridge",
        "command_id": command.get("id"),
        "stdout": stdout.getvalue(),
        "duration_s": round(time.time() - started, 3),
    })
    if error:
        payload["error"] = error
    _write_json(result_path, payload)

    command_path = command.get("command_path")
    if command_path:
        with contextlib.suppress(Exception):
            Path(command_path).unlink()


def run(context) -> None:
    global _app, _watcher
    _app = adsk.core.Application.get()
    event = _app.registerCustomEvent(EVENT_ID)
    handler = _CommandHandler()
    event.add(handler)
    _handlers.append(handler)
    _stop.clear()
    _watcher = threading.Thread(target=_watch_loop, name="sim-fusion360-bridge", daemon=True)
    _watcher.start()
    _write_status("running")


def stop(context) -> None:
    _stop.set()
    try:
        if _app:
            _app.unregisterCustomEvent(EVENT_ID)
    except Exception:
        pass
    _write_status("stopped")
