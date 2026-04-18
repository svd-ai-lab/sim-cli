"""Isaac driver unit tests — no real Isaac install required."""
from __future__ import annotations

from pathlib import Path

import pytest

from sim.drivers.isaac import IsaacDriver

FIX = Path(__file__).parent.parent.parent / "fixtures" / "isaac"


@pytest.fixture
def driver() -> IsaacDriver:
    return IsaacDriver()


class TestDetect:
    @pytest.mark.parametrize("name", [
        "hello_world.py", "import_franka.py", "replicator_cubes.py",
        "warehouse_sdg.py", "bad_no_simapp.py", "bad_import_order.py",
    ])
    def test_detects_isaac_scripts(self, driver, name):
        assert driver.detect(FIX / name) is True

    def test_rejects_plain_python(self, driver):
        assert driver.detect(FIX / "not_isaac.py") is False

    def test_rejects_non_py(self, driver, tmp_path):
        p = tmp_path / "foo.txt"
        p.write_text("from isaacsim import SimulationApp")
        assert driver.detect(p) is False

    def test_rejects_missing_file(self, driver, tmp_path):
        assert driver.detect(tmp_path / "nope.py") is False


class TestLint:
    def test_good_hello_world(self, driver):
        r = driver.lint(FIX / "hello_world.py")
        assert r.ok is True
        assert not any(d.level == "error" for d in r.diagnostics)

    def test_good_replicator(self, driver):
        r = driver.lint(FIX / "replicator_cubes.py")
        assert r.ok is True

    def test_non_py_errors(self, driver, tmp_path):
        p = tmp_path / "foo.txt"
        p.write_text("x")
        r = driver.lint(p)
        assert r.ok is False
        assert any("Unsupported file type" in d.message for d in r.diagnostics)

    def test_empty_errors(self, driver, tmp_path):
        p = tmp_path / "empty.py"
        p.write_text("")
        r = driver.lint(p)
        assert r.ok is False
        assert any("empty" in d.message.lower() for d in r.diagnostics)

    def test_syntax_error(self, driver):
        r = driver.lint(FIX / "syntax_error.py")
        assert r.ok is False
        assert any("Syntax error" in d.message for d in r.diagnostics)

    def test_no_simapp_errors(self, driver):
        r = driver.lint(FIX / "bad_no_simapp.py")
        assert r.ok is False
        assert any("SimulationApp" in d.message for d in r.diagnostics)

    def test_import_order_warns(self, driver):
        r = driver.lint(FIX / "bad_import_order.py")
        assert r.ok is True
        assert any(
            d.level == "warning" and "SimulationApp" in d.message
            for d in r.diagnostics
        )

    def test_no_close_warns(self, driver):
        r = driver.lint(FIX / "bad_no_close.py")
        assert r.ok is True
        assert any("close" in d.message.lower() for d in r.diagnostics)


class TestDetectInstalled:
    def test_no_env_no_import_returns_empty(self, driver, monkeypatch):
        monkeypatch.delenv("ISAAC_PYTHON", raising=False)
        monkeypatch.delenv("ISAAC_VENV", raising=False)

        def fake_probe(_exe):
            return None

        monkeypatch.setattr("sim.drivers.isaac.driver._probe_python", fake_probe)
        assert driver.detect_installed() == []

    def test_env_isaac_python_found(self, driver, monkeypatch, tmp_path):
        fake_py = tmp_path / "python.exe"
        fake_py.write_text("")
        monkeypatch.setenv("ISAAC_PYTHON", str(fake_py))
        monkeypatch.delenv("ISAAC_VENV", raising=False)

        def fake_probe(exe):
            if str(exe) == str(fake_py):
                return "4.5.0"
            return None

        monkeypatch.setattr("sim.drivers.isaac.driver._probe_python", fake_probe)
        installs = driver.detect_installed()
        assert len(installs) >= 1
        matches = [i for i in installs if i.source == "env:ISAAC_PYTHON"]
        assert len(matches) == 1
        assert matches[0].version == "4.5"

    def test_env_isaac_venv_derives_python(self, driver, monkeypatch, tmp_path):
        venv = tmp_path / "v"
        (venv / "Scripts").mkdir(parents=True)
        (venv / "bin").mkdir(parents=True)
        (venv / "Scripts" / "python.exe").write_text("")
        (venv / "bin" / "python").write_text("")
        monkeypatch.delenv("ISAAC_PYTHON", raising=False)
        monkeypatch.setenv("ISAAC_VENV", str(venv))

        def fake_probe(_exe):
            return "4.5.1"

        monkeypatch.setattr("sim.drivers.isaac.driver._probe_python", fake_probe)
        installs = driver.detect_installed()
        matches = [i for i in installs if i.source == "env:ISAAC_VENV"]
        assert len(matches) == 1


class TestConnect:
    def test_not_installed(self, driver, monkeypatch):
        monkeypatch.setattr(driver, "detect_installed", lambda: [])
        info = driver.connect()
        assert info.status == "not_installed"
        assert "uv pip install" in info.message

    def test_installed(self, driver, monkeypatch):
        from sim.driver import SolverInstall
        inst = SolverInstall(
            name="isaac", version="4.5", path="E:/isaac/venv",
            source="env:ISAAC_VENV",
            extra={"python": "E:/isaac/venv/Scripts/python.exe", "raw_version": "4.5.0"},
        )
        monkeypatch.setattr(driver, "detect_installed", lambda: [inst])
        info = driver.connect()
        assert info.status == "ok"
        assert info.version == "4.5"


class TestParseOutput:
    def test_last_json_line(self, driver):
        stdout = 'warning: blah\n{"level": "L1", "delta_z_m": 4.9}'
        assert driver.parse_output(stdout) == {"level": "L1", "delta_z_m": 4.9}

    def test_no_json(self, driver):
        assert driver.parse_output("just logs\nno json") == {}

    def test_multiple_json(self, driver):
        stdout = '{"first": 1}\nnoise\n{"second": 2}'
        assert driver.parse_output(stdout) == {"second": 2}


class TestRunFile:
    def test_raises_when_not_installed(self, driver, monkeypatch, tmp_path):
        monkeypatch.setattr(driver, "detect_installed", lambda: [])
        p = tmp_path / "s.py"
        p.write_text("from isaacsim import SimulationApp\nSimulationApp({})")
        with pytest.raises(RuntimeError, match="not installed|Isaac Sim"):
            driver.run_file(p)

    def test_raises_on_non_py(self, driver, tmp_path):
        p = tmp_path / "s.txt"
        p.write_text("x")
        with pytest.raises(RuntimeError, match="only accepts .py"):
            driver.run_file(p)
