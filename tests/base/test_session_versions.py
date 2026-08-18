"""Active-runtime version and compatibility-layer contract tests."""
from __future__ import annotations

from fastapi.testclient import TestClient

from sim.compat import Compatibility, Profile
from sim.driver import SolverInstall


class _VersionedDriver:
    name = "versioned"
    supports_session = True

    def launch(self, **_kwargs):
        return {
            "ok": True,
            "session_id": "versioned-session",
            "solver_version": "24.1",
            "sdk_version": "0.37.2",
        }

    def detect_installed(self):
        return [
            SolverInstall(
                name=self.name,
                version="25.2",
                path="C:/solver/25.2",
                source="test",
            )
        ]

    def disconnect(self):
        return {"ok": True}


class _FailedDriver:
    name = "failed"
    supports_session = True

    def launch(self, **_kwargs):
        return {
            "ok": False,
            "error_code": "SOLVER_NOT_INSTALLED",
            "message": "solver is unavailable",
        }


def _profile(name: str, version: str, sdk: str, solver: str) -> Profile:
    return Profile(
        name=name,
        sdk="sdk-package",
        solver_versions=(version,),
        active_sdk_layer=sdk,
        active_solver_layer=solver,
    )


def test_runtime_version_wins_over_newer_detected_install(monkeypatch) -> None:
    from sim import compat as compat_mod
    from sim import server

    old = _profile("old-runtime", "24.1", "0.37", "24.1")
    newest = _profile("newest-install", "25.2", "0.38", "25.2")
    compatibility = Compatibility(
        driver="versioned",
        sdk_package="sdk-package",
        profiles=(old, newest),
    )
    monkeypatch.setattr(
        compat_mod,
        "load_compatibility_by_name",
        lambda _solver: compatibility,
    )

    resolved = server._resolve_profile(
        _VersionedDriver(),
        "versioned",
        solver_version="24.1",
    )

    assert resolved is old


def test_session_versions_reports_active_runtime(monkeypatch) -> None:
    from sim import compat as compat_mod
    from sim import drivers as drivers_mod
    from sim import server

    runtime_profile = _profile("old-runtime", "24.1", "0.37", "24.1")
    monkeypatch.setattr(
        compat_mod,
        "load_compatibility_by_name",
        lambda _solver: Compatibility(
            driver="versioned",
            sdk_package="sdk-package",
            profiles=(runtime_profile,),
        ),
    )
    monkeypatch.setattr(
        compat_mod,
        "find_profile",
        lambda name: ("versioned", runtime_profile)
        if name == runtime_profile.name
        else None,
    )
    monkeypatch.setattr(
        drivers_mod,
        "get_driver",
        lambda name: _VersionedDriver() if name == "versioned" else None,
    )
    server._sessions.clear()
    client = TestClient(server.app)

    response = client.post(
        "/connect",
        json={"solver": "versioned", "mode": "solver", "ui_mode": "no_gui"},
    )
    assert response.status_code == 200, response.text
    connect_data = response.json()["data"]
    assert connect_data["solver_version"] == "24.1"
    assert connect_data["profile"] == "old-runtime"

    versions = client.get("/inspect/session.versions")
    assert versions.status_code == 200, versions.text
    data = versions.json()["data"]
    assert data == {
        "solver": "versioned",
        "solver_version": "24.1",
        "sdk_version": "0.37.2",
        "profile": "old-runtime",
        "active_sdk_layer": "0.37",
        "active_solver_layer": "24.1",
        "version_source": "active_runtime",
    }

    server._sessions.clear()


def test_structured_launch_failure_does_not_register_session(monkeypatch) -> None:
    from sim import drivers as drivers_mod
    from sim import server

    monkeypatch.setattr(
        drivers_mod,
        "get_driver",
        lambda name: _FailedDriver() if name == "failed" else None,
    )
    server._sessions.clear()
    client = TestClient(server.app)

    response = client.post(
        "/connect",
        json={"solver": "failed", "mode": "solver", "ui_mode": "no_gui"},
    )

    assert response.status_code == 400
    assert "SOLVER_NOT_INSTALLED" in response.text
    assert server._sessions == {}
