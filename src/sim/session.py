"""Session client — HTTP client that talks to sim-server.

Always HTTP, whether local or remote:
  sim connect --solver pyfluent                    # auto-starts sim-server locally
  sim connect --solver pyfluent --host 100.90.x.x  # talks to remote sim-server

If no server is running locally, `connect` auto-starts one as a background process.
"""
from __future__ import annotations

import subprocess
import sys
import time

import httpx

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 7600
CONNECT_TIMEOUT_S = 180
CMD_TIMEOUT_S = 600


class SessionClient:
    """HTTP client for sim-server. Works with local or remote servers."""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self._base = f"http://{host}:{port}"
        self._host = host
        self._port = port

    def _is_local(self) -> bool:
        return self._host in ("localhost", "127.0.0.1")

    def _server_reachable(self) -> bool:
        try:
            with httpx.Client(timeout=3) as c:
                r = c.get(f"{self._base}/ps")
                return r.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False

    def _auto_start_server(self) -> bool:
        """Start sim-server locally as a background process."""
        cmd = [sys.executable, "-c",
               "import uvicorn; from sim.server import app; "
               f"uvicorn.run(app, host='127.0.0.1', port={self._port}, log_level='warning')"]

        try:
            if sys.platform == "win32":
                CREATE_NEW_PROCESS_GROUP = 0x00000200
                DETACHED_PROCESS = 0x00000008
                subprocess.Popen(cmd,
                                 creationflags=CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS,
                                 close_fds=True)
            else:
                subprocess.Popen(cmd, start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 close_fds=True)
        except Exception:
            return False

        # Wait for server to become reachable
        deadline = time.time() + 10
        while time.time() < deadline:
            if self._server_reachable():
                return True
            time.sleep(0.3)
        return False

    def _request(self, method: str, path: str, timeout: float = CMD_TIMEOUT_S, **kwargs) -> dict:
        try:
            with httpx.Client(timeout=timeout) as c:
                r = getattr(c, method)(f"{self._base}{path}", **kwargs)
                data = r.json()
                if r.status_code >= 400:
                    return {"ok": False, "error": data.get("detail", str(data))}
                return data
        except httpx.ConnectError:
            return {"ok": False, "error": f"cannot reach sim-server at {self._base}"}
        except httpx.TimeoutException:
            return {"ok": False, "error": f"request timed out after {timeout}s"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def connect(self, solver: str, mode: str = "meshing",
                ui_mode: str = "no_gui", processors: int = 1,
                profile: str | None = None, inline: bool = False) -> dict:
        # Auto-start local server if needed
        if self._is_local() and not self._server_reachable():
            if not self._auto_start_server():
                return {"ok": False, "error": "failed to auto-start sim-server locally"}

        body: dict = {
            "solver": solver, "mode": mode,
            "ui_mode": ui_mode, "processors": processors,
        }
        if profile:
            body["profile"] = profile
        if inline:
            body["inline"] = True
        return self._request("post", "/connect", timeout=CONNECT_TIMEOUT_S, json=body)

    def run(self, code: str, label: str = "cli-snippet") -> dict:
        return self._request("post", "/exec", json={"code": code, "label": label})

    def query(self, name: str) -> dict:
        return self._request("get", f"/inspect/{name}", timeout=30)

    def disconnect(self) -> dict:
        return self._request("post", "/disconnect", timeout=30)

    def status(self) -> dict:
        return self._request("get", "/ps", timeout=10)

    def screenshot(self) -> dict:
        return self._request("get", "/screenshot", timeout=30)
