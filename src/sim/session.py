"""Session client — HTTP client that talks to sim-server.

Always HTTP, whether local or remote:
  sim connect --solver pyfluent                    # auto-starts sim-server locally
  sim connect --solver pyfluent --host 100.90.x.x  # talks to remote sim-server

If no server is running locally, `connect` auto-starts one as a background process.

Multi-session (issue #26): the client carries an optional `session_id`. When
set, every per-session call (`run`, `query`, `disconnect`, `screenshot`)
sends `X-Sim-Session: <id>`. When unset, the server picks the sole live
session as default — so single-session callers work unchanged.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import httpx

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 7600
CONNECT_TIMEOUT_S = 180
CMD_TIMEOUT_S = 600


def _local_hosts() -> set[str]:
    return {"localhost", "127.0.0.1", "::1", ""}


def _httpx_client(host: str, timeout: float) -> httpx.Client:
    """Build an httpx Client that bypasses system proxies for localhost.

    Windows workstations often run a system-wide proxy (Privoxy, Clash, etc.)
    which happily intercepts 127.0.0.1:* calls and returns garbage. Setting
    trust_env=False for localhost targets sidesteps all of that.
    """
    if host in _local_hosts():
        return httpx.Client(timeout=timeout, trust_env=False)
    return httpx.Client(timeout=timeout)


class SessionClient:
    """HTTP client for sim-server. Works with local or remote servers.

    `session_id` is used as the `X-Sim-Session` header on per-session
    endpoints. Leave it None to use the server's default-picking rules
    (works whenever exactly one session is live).
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        session_id: str | None = None,
    ):
        self._base = f"http://{host}:{port}"
        self._host = host
        self._port = port
        self.session_id = session_id

    def _is_local(self) -> bool:
        return self._host in ("localhost", "127.0.0.1")

    def _server_reachable(self) -> bool:
        try:
            with _httpx_client(self._host, timeout=3) as c:
                r = c.get(f"{self._base}/ps")
                return r.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException, httpx.ReadTimeout):
            return False

    def _auto_start_server(self) -> bool:
        """Start sim-server locally as a background process.

        On Windows DETACHED_PROCESS hides the console — so any write to
        stdout/stderr from uvicorn (or any import-time print) crashes the
        subprocess. Redirecting stdio to DEVNULL avoids that.
        """
        import os
        sim_dir = Path(os.environ.get("SIM_DIR") or (Path.cwd() / ".sim"))
        sim_dir.mkdir(parents=True, exist_ok=True)
        log_path = sim_dir / "sim-serve.log"

        cmd = [sys.executable, "-c",
               "import uvicorn; from sim.server import app; "
               f"uvicorn.run(app, host='127.0.0.1', port={self._port}, log_level='warning')"]

        try:
            log_fh = open(log_path, "ab")
            if sys.platform == "win32":
                CREATE_NEW_PROCESS_GROUP = 0x00000200
                DETACHED_PROCESS = 0x00000008
                subprocess.Popen(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=log_fh,
                    stderr=log_fh,
                    creationflags=CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS,
                    close_fds=True,
                )
            else:
                subprocess.Popen(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=log_fh,
                    stderr=log_fh,
                    start_new_session=True,
                    close_fds=True,
                )
        except Exception:
            return False

        # Wait for server to become reachable
        deadline = time.time() + 15
        while time.time() < deadline:
            if self._server_reachable():
                return True
            time.sleep(0.3)
        return False

    def _session_headers(self) -> dict[str, str]:
        return {"X-Sim-Session": self.session_id} if self.session_id else {}

    def _request(
        self,
        method: str,
        path: str,
        *,
        timeout: float = CMD_TIMEOUT_S,
        session_scoped: bool = False,
        **kwargs,
    ) -> dict:
        headers = kwargs.pop("headers", {}) or {}
        if session_scoped:
            headers = {**self._session_headers(), **headers}
        try:
            with _httpx_client(self._host, timeout=timeout) as c:
                r = getattr(c, method)(f"{self._base}{path}", headers=headers, **kwargs)
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
                workspace: str | None = None,
                driver_options: dict | None = None) -> dict:
        # Auto-start local server if needed
        if self._is_local() and not self._server_reachable():
            if not self._auto_start_server():
                return {"ok": False, "error": "failed to auto-start sim-server locally"}

        body: dict = {
            "solver": solver, "mode": mode,
            "ui_mode": ui_mode, "processors": processors,
        }
        if workspace is not None:
            body["workspace"] = workspace
        if driver_options:
            body["driver_options"] = driver_options
        resp = self._request("post", "/connect", timeout=CONNECT_TIMEOUT_S, json=body)
        # Remember the new session_id so subsequent calls on this client
        # route to it even if another session shows up later.
        if resp.get("ok"):
            new_sid = (resp.get("data") or {}).get("session_id")
            if new_sid:
                self.session_id = new_sid
        return resp

    def run(self, code: str, label: str = "cli-snippet") -> dict:
        return self._request(
            "post", "/exec",
            json={"code": code, "label": label},
            session_scoped=True,
        )

    def query(self, name: str) -> dict:
        return self._request(
            "get", f"/inspect/{name}",
            timeout=30,
            session_scoped=True,
        )

    def disconnect(self) -> dict:
        return self._request(
            "post", "/disconnect",
            timeout=30,
            session_scoped=True,
        )

    def stop(self) -> dict:
        """Stop the sim-server process itself (tears down all sessions).

        POSTs /shutdown. The server tears down active sessions, flushes
        the response, then exits cleanly via os._exit(0). Because the
        process dies mid-stream, the connection often closes before we
        read the body — that's expected, treat it as success.
        """
        try:
            with _httpx_client(self._host, timeout=10) as c:
                r = c.post(f"{self._base}/shutdown")
                try:
                    return r.json()
                except Exception:
                    return {"ok": True, "data": {"shutting_down": True}}
        except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError):
            return {"ok": True, "data": {"shutting_down": True}}
        except httpx.TimeoutException:
            return {"ok": False, "error": "timed out waiting for /shutdown"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def status(self) -> dict:
        """GET /ps — returns the multi-session shape {sessions: [...], default_session}."""
        return self._request("get", "/ps", timeout=10)

    def screenshot(self) -> dict:
        return self._request("get", "/screenshot", timeout=30)
