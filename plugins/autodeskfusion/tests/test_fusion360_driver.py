from __future__ import annotations

import json
from pathlib import Path
import time

import pytest

from sim.driver import SolverInstall
from sim_plugin_fusion360 import Fusion360Driver, plugin_info, skills_dir


FIXTURES = Path(__file__).parent / "fixtures"


def test_plugin_metadata_exports():
    assert plugin_info["name"] == "fusion360"
    assert skills_dir.name == "_skills"


class TestDetect:
    def test_detects_adsk_script(self):
        assert Fusion360Driver().detect(FIXTURES / "good_fusion_script.py") is True

    def test_rejects_plain_python(self):
        assert Fusion360Driver().detect(FIXTURES / "not_fusion.py") is False

    def test_missing_is_false(self):
        assert Fusion360Driver().detect(Path("/no/such/fusion.py")) is False


class TestLint:
    def test_good_script(self):
        result = Fusion360Driver().lint(FIXTURES / "good_fusion_script.py")
        assert result.ok is True

    def test_plain_python_warns_but_is_valid_python(self):
        result = Fusion360Driver().lint(FIXTURES / "not_fusion.py")
        assert result.ok is True
        assert any("adsk" in d.message for d in result.diagnostics)

    def test_bad_syntax(self):
        result = Fusion360Driver().lint(FIXTURES / "bad_syntax.py")
        assert result.ok is False
        assert result.diagnostics[0].line == 2

    def test_wrong_suffix(self, tmp_path):
        path = tmp_path / "model.txt"
        path.write_text("import adsk.core\n")
        assert Fusion360Driver().lint(path).ok is False


class TestConnect:
    def test_not_installed(self, monkeypatch):
        driver = Fusion360Driver()
        monkeypatch.setattr(driver, "detect_installed", lambda: [])
        info = driver.connect()
        assert info.status == "not_installed"
        assert "SIM_FUSION360_EXE" in info.message

    def test_found(self, monkeypatch, tmp_path):
        driver = Fusion360Driver(session_dir=tmp_path)
        monkeypatch.setattr(
            driver,
            "detect_installed",
            lambda: [SolverInstall(
                name="fusion360",
                version="2702.1.58",
                path="/fake",
                source="test",
                extra={"exe": "/fake/Fusion360.exe"},
            )],
        )
        info = driver.connect()
        assert info.status == "ok"
        assert info.version == "2702.1.58"


def test_detect_installed_from_env(monkeypatch, tmp_path):
    exe = tmp_path / "Fusion360.exe"
    exe.write_text("fake exe")
    api = tmp_path / "Autodesk Fusion 360" / "API"
    api.mkdir(parents=True)
    (api.parent / "Fusion360_2702.1.58_addins_to_load.xml").write_text("<xml />")

    monkeypatch.setenv("SIM_FUSION360_EXE", str(exe))
    monkeypatch.setattr("sim_plugin_fusion360.driver._default_windows_exes", lambda: [])
    monkeypatch.setattr("sim_plugin_fusion360.driver._default_macos_exes", lambda: [])

    [install] = Fusion360Driver(api_dir=api).detect_installed()
    assert install.name == "fusion360"
    assert install.version == "2702.1.58"
    assert install.source == "env:SIM_FUSION360_EXE"
    assert install.extra["exe"] == str(exe)


def test_parse_output_last_json_wins():
    out = Fusion360Driver().parse_output('banner\n{"old": false}\n{"ok": true}\n')
    assert out == {"ok": True}


def test_install_bridge_copies_resources(tmp_path):
    api = tmp_path / "API"
    bridge_dir = Fusion360Driver(api_dir=api).install_bridge()
    assert (bridge_dir / "SimFusionBridge.py").is_file()
    assert (bridge_dir / "SimFusionBridge.manifest").is_file()


class TestRunFile:
    def test_wrong_suffix_raises(self, tmp_path):
        path = tmp_path / "x.txt"
        path.write_text("import adsk.core\n")
        with pytest.raises(RuntimeError, match=r"\.py"):
            Fusion360Driver().run_file(path)

    def test_bridge_not_running_raises(self):
        with pytest.raises(RuntimeError, match="bridge is not running"):
            Fusion360Driver().run_file(FIXTURES / "good_fusion_script.py")

    def test_stages_command_and_returns_run_result(self, monkeypatch, tmp_path):
        driver = Fusion360Driver(session_dir=tmp_path)
        monkeypatch.setattr(driver, "_bridge_is_running", lambda: True)

        def fake_wait(result_path, timeout_s):
            return {"ok": True, "body_count": 1, "result_path": str(result_path)}

        monkeypatch.setattr(driver, "_wait_for_result", fake_wait)
        result = driver.run_file(FIXTURES / "good_fusion_script.py")
        assert result.exit_code == 0
        parsed = driver.parse_output(result.stdout)
        assert parsed["body_count"] == 1

        [command_path] = (tmp_path / "queue").glob("*.json")
        command = json.loads(command_path.read_text())
        assert command["kind"] == "script_file"
        assert command["script"].endswith("good_fusion_script.py")
        assert "SIM_FUSION360_OUT" in command["env"]

    def test_code_session_run(self, monkeypatch, tmp_path):
        driver = Fusion360Driver(session_dir=tmp_path)
        monkeypatch.setattr(driver, "_bridge_is_running", lambda: True)
        monkeypatch.setattr(driver, "_wait_for_result", lambda _p, _t: {"ok": True, "stdout": "hi"})
        result = driver.run("print('hi')", label="unit")
        assert result == {"ok": True, "stdout": "hi"}


def test_bridge_status_staleness(tmp_path):
    driver = Fusion360Driver(session_dir=tmp_path)
    driver.session_dir.mkdir(parents=True, exist_ok=True)
    (driver.session_dir / "bridge_status.json").write_text(json.dumps({
        "status": "running",
        "heartbeat": time.time() - 60,
    }))
    assert driver._bridge_is_running() is False

    (driver.session_dir / "bridge_status.json").write_text(json.dumps({
        "status": "running",
        "heartbeat": time.time(),
    }))
    assert driver._bridge_is_running() is True
