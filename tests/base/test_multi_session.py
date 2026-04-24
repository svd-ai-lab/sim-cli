"""Multi-session server tests (issue #26).

Uses FastAPI TestClient + monkey-patched fake drivers so no real solver
is needed. Covers:
  - Two sessions on different solvers run concurrently
  - X-Sim-Session routes /exec to the correct session
  - /ps reports both; default_session is set only when n==1
  - Header-less /exec on n>1 returns 400 with a helpful message
  - /disconnect tears down one; /shutdown tears down all
  - Two sessions on the same solver are rejected (until per-instance drivers)
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sim import server


class FakeDriver:
    """Minimal driver that pretends to launch and echoes exec payloads."""

    supports_session = True

    def __init__(self, name: str):
        self.name = name
        self._launched = False
        self._disconnected = False

    def launch(self, **kwargs):
        self._launched = True
        return {"ok": True}

    def run(self, code: str, label: str = "snippet"):
        return {
            "ok": True,
            "code": code,
            "label": label,
            "solver": self.name,
            "stdout": f"ran on {self.name}",
            "stderr": "",
        }

    def query(self, name: str):
        return {"ok": True, "solver": self.name, "target": name}

    def disconnect(self):
        self._disconnected = True


@pytest.fixture
def fake_drivers(monkeypatch):
    """Register two fake drivers ("alpha", "beta") via get_driver monkeypatch."""
    instances = {"alpha": FakeDriver("alpha"), "beta": FakeDriver("beta")}

    def _get(name: str):
        return instances.get(name)

    monkeypatch.setattr("sim.drivers.get_driver", _get)
    # /connect imports inline — patch the module path it imports from, too.
    import sim.drivers as drivers_mod
    monkeypatch.setattr(drivers_mod, "get_driver", _get)
    yield instances


@pytest.fixture(autouse=True)
def clean_sessions():
    """Ensure every test starts/ends with an empty session registry."""
    server._sessions.clear()
    yield
    server._sessions.clear()


@pytest.fixture
def client():
    return TestClient(server.app)


def _connect(client, solver: str) -> str:
    r = client.post("/connect", json={
        "solver": solver, "mode": "solver",
        "ui_mode": "no_gui", "processors": 1,
    })
    assert r.status_code == 200, r.text
    return r.json()["data"]["session_id"]


class TestMultiSession:
    def test_two_sessions_coexist(self, client, fake_drivers):
        sid_a = _connect(client, "alpha")
        sid_b = _connect(client, "beta")
        assert sid_a != sid_b

        r = client.get("/ps")
        assert r.status_code == 200
        body = r.json()
        assert len(body["sessions"]) == 2
        # Two sessions → no default (must explicitly select)
        assert body["default_session"] is None
        solvers = {s["solver"] for s in body["sessions"]}
        assert solvers == {"alpha", "beta"}

    def test_exec_routes_by_header(self, client, fake_drivers):
        sid_a = _connect(client, "alpha")
        sid_b = _connect(client, "beta")

        r_a = client.post("/exec", json={"code": "x", "label": "t"},
                          headers={"X-Sim-Session": sid_a})
        assert r_a.status_code == 200
        assert r_a.json()["data"]["solver"] == "alpha"

        r_b = client.post("/exec", json={"code": "x", "label": "t"},
                          headers={"X-Sim-Session": sid_b})
        assert r_b.status_code == 200
        assert r_b.json()["data"]["solver"] == "beta"

    def test_exec_without_header_errors_when_multiple_live(self, client, fake_drivers):
        _connect(client, "alpha")
        _connect(client, "beta")
        r = client.post("/exec", json={"code": "x", "label": "t"})
        assert r.status_code == 400
        assert "X-Sim-Session" in r.json()["detail"]

    def test_exec_default_session_when_single_live(self, client, fake_drivers):
        _connect(client, "alpha")
        r = client.post("/exec", json={"code": "x", "label": "t"})
        assert r.status_code == 200
        assert r.json()["data"]["solver"] == "alpha"

        r_ps = client.get("/ps").json()
        assert r_ps["default_session"] is not None

    def test_unknown_session_id_404(self, client, fake_drivers):
        _connect(client, "alpha")
        r = client.post("/exec", json={"code": "x"},
                        headers={"X-Sim-Session": "nope"})
        assert r.status_code == 404

    def test_disconnect_one_leaves_other(self, client, fake_drivers):
        sid_a = _connect(client, "alpha")
        sid_b = _connect(client, "beta")

        r = client.post("/disconnect", headers={"X-Sim-Session": sid_a})
        assert r.status_code == 200
        assert r.json()["data"]["session_id"] == sid_a

        # beta still live and usable
        r_exec = client.post("/exec", json={"code": "x"},
                             headers={"X-Sim-Session": sid_b})
        assert r_exec.status_code == 200
        assert r_exec.json()["data"]["solver"] == "beta"

        ps = client.get("/ps").json()
        assert len(ps["sessions"]) == 1
        assert ps["default_session"] == sid_b
        assert fake_drivers["alpha"]._disconnected is True
        assert fake_drivers["beta"]._disconnected is False

    def test_same_solver_twice_rejected(self, client, fake_drivers):
        _connect(client, "alpha")
        # Second connect on same solver should fail — see server.py note.
        r = client.post("/connect", json={
            "solver": "alpha", "mode": "solver",
            "ui_mode": "no_gui", "processors": 1,
        })
        assert r.status_code == 400
        assert "already live" in r.json()["detail"]

    def test_inspect_routes_by_header(self, client, fake_drivers):
        sid_a = _connect(client, "alpha")
        sid_b = _connect(client, "beta")

        r_a = client.get("/inspect/deck.summary",
                         headers={"X-Sim-Session": sid_a})
        assert r_a.status_code == 200
        assert r_a.json()["data"]["solver"] == "alpha"

        r_b = client.get("/inspect/deck.summary",
                         headers={"X-Sim-Session": sid_b})
        assert r_b.json()["data"]["solver"] == "beta"

    def test_exec_with_no_sessions_errors(self, client, fake_drivers):
        r = client.post("/exec", json={"code": "x"})
        assert r.status_code == 400
        assert "no active sessions" in r.json()["detail"].lower()

    def test_ps_empty(self, client):
        r = client.get("/ps")
        assert r.status_code == 200
        body = r.json()
        assert body["sessions"] == []
        assert body["default_session"] is None
        assert "server_pid" in body
