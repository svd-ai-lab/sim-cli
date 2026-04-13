"""Tests for the MATLAB driver."""
from pathlib import Path
from types import SimpleNamespace

from sim.drivers.matlab import MatlabDriver

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "matlab"


class TestMatlabDetect:
    def test_detects_m_script(self):
        driver = MatlabDriver()
        assert driver.detect(FIXTURES / "matlab_ok.m") is True

    def test_rejects_python_script(self):
        driver = MatlabDriver()
        assert driver.detect(FIXTURES.parent / "mock_solver.py") is False


class TestMatlabParseOutput:
    def test_parses_last_json_line(self):
        driver = MatlabDriver()
        payload = driver.parse_output("hello\n{\"status\":\"ok\",\"value\":42}\n")
        assert payload["status"] == "ok"
        assert payload["value"] == 42


class TestMatlabConnect:
    def test_reports_not_installed_when_missing(self, monkeypatch):
        monkeypatch.setattr("sim.drivers.matlab.driver.shutil.which", lambda _: None)
        driver = MatlabDriver()
        info = driver.connect()
        assert info.status == "not_installed"


class TestMatlabRunFile:
    def test_uses_matlab_batch(self, monkeypatch):
        monkeypatch.setattr(
            "sim.drivers.matlab.driver.shutil.which",
            lambda _: "/usr/local/bin/matlab",
        )

        recorded = {}

        def fake_run(command, capture_output, text):
            recorded["command"] = command
            return SimpleNamespace(returncode=0, stdout='{"status":"ok"}\n', stderr="")

        monkeypatch.setattr("sim.runner.subprocess.run", fake_run)

        driver = MatlabDriver()
        result = driver.run_file(FIXTURES / "matlab_ok.m")
        assert result.exit_code == 0
        assert recorded["command"][0] == "/usr/local/bin/matlab"
        assert recorded["command"][1] == "-batch"


class TestMatlabLint:
    def test_lint_returns_install_error_when_matlab_missing(self, monkeypatch):
        monkeypatch.setattr("sim.drivers.matlab.driver.shutil.which", lambda _: None)
        driver = MatlabDriver()
        result = driver.lint(FIXTURES / "matlab_ok.m")
        assert result.ok is False
        assert "not available" in result.diagnostics[0].message.lower()


class TestReleaseEngineMap:
    """Every MATLAB release sim-cli claims to support must resolve to a
    concrete matlabengine pip version — otherwise detect_installed()
    reports engine_version='?', compat.yaml lookup silently fails, and
    `sim env install matlab` emits `pip install matlabengine==?`.
    """

    def test_known_releases_resolve(self):
        from sim.drivers.matlab.driver import _engine_version_for

        assert _engine_version_for("R2025b") == "25.2"
        assert _engine_version_for("R2025a") == "25.1"
        assert _engine_version_for("R2024b") == "24.2"
        assert _engine_version_for("R2024a") == "24.1"

    def test_unknown_release_returns_none(self):
        from sim.drivers.matlab.driver import _engine_version_for

        assert _engine_version_for("R2099z") is None
