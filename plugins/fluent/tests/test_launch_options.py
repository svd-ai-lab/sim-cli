from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from sim_plugin_fluent import PyFluentDriver


class _Config:
    launch_fluent_ip = None


class _FakeSession:
    def exit(self) -> None:
        pass


def _install_fake_pyfluent(monkeypatch: pytest.MonkeyPatch, calls: list[dict]) -> None:
    ansys = types.ModuleType("ansys")
    fluent = types.ModuleType("ansys.fluent")
    core = types.ModuleType("ansys.fluent.core")
    core.__version__ = "0.38.1"
    core.config = _Config()

    def launch_fluent(**kwargs):
        calls.append(kwargs)
        return _FakeSession()

    core.launch_fluent = launch_fluent
    core.connect_to_fluent = lambda **_kwargs: _FakeSession()
    fluent.core = core
    ansys.fluent = fluent

    monkeypatch.setitem(sys.modules, "ansys", ansys)
    monkeypatch.setitem(sys.modules, "ansys.fluent", fluent)
    monkeypatch.setitem(sys.modules, "ansys.fluent.core", core)


def test_launch_forwards_normalized_fluent_options(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[dict] = []
    _install_fake_pyfluent(monkeypatch, calls)

    driver = PyFluentDriver(sim_dir=tmp_path / ".sim")
    result = driver.launch(
        mode="solver",
        ui_mode="no_gui",
        dimension=2,
        precision="double",
        processor_count=4,
        cwd=tmp_path,
    )

    assert result["ok"] is True
    assert calls == [
        {
            "ui_mode": "no_gui",
            "precision": "double",
            "mode": "solver",
            "dimension": 2,
            "processor_count": 4,
            "cwd": str(tmp_path.resolve()),
        }
    ]
    assert result["launch_options"] == {
        "mode": "solver",
        "ui_mode": "no_gui",
        "dimension": 2,
        "precision": "double",
        "processor_count": 4,
        "cwd": str(tmp_path.resolve()),
    }
    assert driver.query("session.summary")["launch_options"] == result["launch_options"]


def test_launch_processors_alias_remains_supported(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[dict] = []
    _install_fake_pyfluent(monkeypatch, calls)

    driver = PyFluentDriver(sim_dir=tmp_path / ".sim")
    driver.launch(
        mode="solver",
        ui_mode="no_gui",
        processors=2,
        precision="single",
    )

    assert calls[0]["processor_count"] == 2
    assert calls[0]["precision"] == "single"


def test_launch_workspace_alias_maps_to_cwd(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[dict] = []
    _install_fake_pyfluent(monkeypatch, calls)

    driver = PyFluentDriver(sim_dir=tmp_path / ".sim")
    result = driver.launch(
        mode="solver",
        ui_mode="no_gui",
        workspace=tmp_path,
    )

    assert calls[0]["cwd"] == str(tmp_path.resolve())
    assert result["launch_options"]["cwd"] == str(tmp_path.resolve())


def test_launch_rejects_conflicting_processor_arguments(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_fake_pyfluent(monkeypatch, [])
    driver = PyFluentDriver(sim_dir=tmp_path / ".sim")

    with pytest.raises(ValueError, match="processors and processor_count disagree"):
        driver.launch(
            mode="solver",
            ui_mode="no_gui",
            processors=2,
            processor_count=4,
        )


def test_launch_rejects_unknown_fluent_options(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_fake_pyfluent(monkeypatch, [])
    driver = PyFluentDriver(sim_dir=tmp_path / ".sim")

    with pytest.raises(ValueError, match="unknown Fluent launch option"):
        driver.launch(mode="solver", ui_mode="no_gui", unsupported=True)


def test_run_artifact_roles_include_fluent_pdf_fla_and_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_fake_pyfluent(monkeypatch, [])
    driver = PyFluentDriver(sim_dir=tmp_path / ".sim")
    driver.launch(mode="solver", ui_mode="no_gui", cwd=tmp_path)

    code = f"""
from pathlib import Path
root = Path(r"{tmp_path}")
(root / "table.pdf").write_text("pdf")
(root / "chem.fla").write_text("fla")
(root / "result.json").write_text("{{}}")
_result = {{"status": "ok"}}
"""
    result = driver.run(code, label="artifact-role-test")

    assert result["ok"] is True
    roles = {Path(a["path"]).name: a["role"] for a in result["artifacts"]}
    assert roles["table.pdf"] == "pdf-table"
    assert roles["chem.fla"] == "flamelet"
    assert roles["result.json"] == "result-json"
