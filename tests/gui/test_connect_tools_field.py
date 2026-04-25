"""Contract test: ``/connect`` advertises ``tools: ["gui"]`` when the
driver created a ``GuiController`` at launch time.

We avoid standing up a real Fluent/COMSOL session (neither is available
in CI) by registering a fake driver whose ``launch()`` constructs a
``sim.gui.GuiController`` into ``self._gui`` — exactly the contract the
server reads when building the response.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


class _FakeDriver:
    """Minimal DriverProtocol stub sufficient for /connect."""
    name = "fakegui"
    supports_session = True

    def __init__(self):
        self._gui = None

    def launch(self, mode="solver", ui_mode="gui", processors=2):
        # Simulate what a real driver does at launch time.
        from sim.gui import GuiController
        self._gui = GuiController(process_name_substrings=("fake",))
        return {"session_id": "fake-session-1"}

    def disconnect(self):
        self._gui = None
        return {"ok": True}


class _FakeDriverNoGui:
    """Mirror of _FakeDriver but does NOT construct a GuiController."""
    name = "fakenogui"
    supports_session = True

    def __init__(self):
        self._gui = None

    def launch(self, mode="solver", ui_mode="no_gui", processors=2):
        return {"session_id": "fake-session-2"}

    def disconnect(self):
        return {"ok": True}


@pytest.fixture
def client(monkeypatch):
    """TestClient with an in-memory fake driver registry + clean state."""
    from sim import server as srv

    def _get_driver(name):
        if name == "fakegui":
            return _FakeDriver()
        if name == "fakenogui":
            return _FakeDriverNoGui()
        return None

    monkeypatch.setattr("sim.drivers.get_driver", _get_driver)
    monkeypatch.setattr(srv, "_resolve_profile", lambda driver, solver: None)

    # Reset global state in case another test left something
    srv._sessions.clear()

    return TestClient(srv.app)


def test_connect_advertises_gui_tool(client):
    r = client.post("/connect", json={
        "solver": "fakegui", "mode": "solver", "ui_mode": "gui", "processors": 2,
    })
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["tools"] == ["gui"]
    assert data["tool_refs"] == {"gui": "sim-skills/sim-cli/gui/SKILL.md"}


def test_connect_omits_tool_when_no_gui(client):
    r = client.post("/connect", json={
        "solver": "fakenogui", "mode": "solver", "ui_mode": "no_gui", "processors": 2,
    })
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["tools"] == []
    assert data["tool_refs"] == {}
