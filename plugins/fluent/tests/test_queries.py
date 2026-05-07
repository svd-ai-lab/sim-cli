from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest
from sim.driver import SolverInstall

from sim_plugin_fluent import PyFluentDriver


class _Config:
    launch_fluent_ip = None


class _Value:
    def __init__(self, value):
        self._value = value

    def get_state(self):
        return self._value


class _BoundaryFamily:
    def __init__(self, names: list[str]):
        self.child_names = names


class _FieldData:
    def get_scalar_field_names(self):
        return ["temperature", "pressure"]

    def get_vector_field_names(self):
        return ["velocity"]


class _Fields:
    field_data = _FieldData()

    def get_surfaces_info(self):
        return {"outlet": {}, "cold-inlet": {}}


class _Models:
    energy = types.SimpleNamespace(enabled=_Value(True))
    viscous = types.SimpleNamespace(model=_Value("k-omega"))
    species = types.SimpleNamespace(model=_Value("species-transport"))


class _BoundaryConditions:
    velocity_inlet = _BoundaryFamily(["cold-inlet", "hot-inlet"])
    pressure_outlet = _BoundaryFamily(["outlet"])
    wall = _BoundaryFamily(["wall"])


class _Setup:
    models = _Models()
    boundary_conditions = _BoundaryConditions()
    mesh = types.SimpleNamespace(child_names=["cell_zones", "face_zones"])


class _File:
    def read_case(self, file_name: str):
        return file_name

    def write_case(self, file_name: str):
        return file_name


class _Settings:
    file = _File()


class _FakeSession:
    fields = _Fields()
    setup = _Setup()
    settings = _Settings()
    workflow = types.SimpleNamespace(child_names=["Import Geometry"])

    def exit(self) -> None:
        pass


def _install_fake_pyfluent(monkeypatch: pytest.MonkeyPatch) -> None:
    ansys = types.ModuleType("ansys")
    fluent = types.ModuleType("ansys.fluent")
    core = types.ModuleType("ansys.fluent.core")
    core.__version__ = "0.38.1"
    core.config = _Config()
    core.launch_fluent = lambda **_kwargs: _FakeSession()
    core.connect_to_fluent = lambda **_kwargs: _FakeSession()
    fluent.core = core
    ansys.fluent = fluent

    monkeypatch.setitem(sys.modules, "ansys", ansys)
    monkeypatch.setitem(sys.modules, "ansys.fluent", fluent)
    monkeypatch.setitem(sys.modules, "ansys.fluent.core", core)


def test_fluent_query_surface_reports_live_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_fake_pyfluent(monkeypatch)
    driver = PyFluentDriver(sim_dir=tmp_path / ".sim")
    driver.launch(mode="solver", ui_mode="no_gui", cwd=tmp_path)
    driver.run("_result = {'status': 'ok'}", label="smoke")

    summary = driver.query("session.summary")
    assert summary["connected"] is True
    assert summary["solver_kind"] == "solver"
    assert summary["run_count"] == 1

    health = driver.query("session.health")
    assert health["ok"] is True
    assert health["interfaces"]["fields"] is True

    fields = driver.query("fluent.field.catalog")
    assert fields["available"] is True
    assert "temperature" in fields["scalar_names"]
    assert "outlet" in fields["surface_names"]

    models = driver.query("fluent.models.summary")
    assert models["models"]["energy"]["enabled"] is True
    assert models["models"]["viscous"]["model"] == "k-omega"

    boundaries = driver.query("fluent.boundaries.summary")
    assert boundaries["families"]["velocity_inlet"] == ["cold-inlet", "hot-inlet"]
    assert boundaries["families"]["pressure_outlet"] == ["outlet"]

    case = driver.query("fluent.case.summary")
    assert case["file_interface_available"] is True
    assert "read_case" in case["file_methods"]

    mesh = driver.query("fluent.mesh.summary")
    assert mesh["available"] is True
    assert "cell_zones" in mesh["children"]


def test_fluent_files_query_classifies_outputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_fake_pyfluent(monkeypatch)
    (tmp_path / "elbow.cas.h5").write_text("case", encoding="utf-8")
    (tmp_path / "elbow.dat.h5").write_text("data", encoding="utf-8")
    (tmp_path / "transcript.trn").write_text("ok", encoding="utf-8")

    driver = PyFluentDriver(sim_dir=tmp_path / ".sim")
    driver.launch(mode="solver", ui_mode="no_gui", cwd=tmp_path)
    files = driver.query("fluent.files")

    roles = {Path(item["path"]).name: item["role"] for item in files["files"]}
    assert roles["elbow.cas.h5"] == "fluent-case"
    assert roles["elbow.dat.h5"] == "fluent-data"
    assert roles["transcript.trn"] == "fluent-transcript"


def test_session_versions_uses_compatibility_layers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_fake_pyfluent(monkeypatch)
    driver = PyFluentDriver(sim_dir=tmp_path / ".sim")
    monkeypatch.setattr(
        driver,
        "detect_installed",
        lambda: [
            SolverInstall(
                name="fluent",
                version="25.2",
                path=str(tmp_path),
                source="test",
                extra={"release_code": "252", "release_label": "2025 R2"},
            )
        ],
    )
    driver.launch(mode="solver", ui_mode="no_gui", cwd=tmp_path)

    versions = driver.query("session.versions")
    assert versions["compatibility"]["active_sdk_layer"] == "0.38"
    assert versions["compatibility"]["active_solver_layer"] == "25.2"
    assert versions["fluent"]["detected"][0]["version"] == "25.2"


def test_detect_and_lint_handle_unreadable_files(tmp_path: Path) -> None:
    missing = tmp_path / "missing.py"
    driver = PyFluentDriver(sim_dir=tmp_path / ".sim")

    assert driver.detect(missing) is False
    lint = driver.lint(missing)
    assert lint.ok is False
    assert lint.diagnostics[0].level == "error"
