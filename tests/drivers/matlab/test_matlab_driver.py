"""Tests for the MATLAB driver."""
from pathlib import Path
from types import SimpleNamespace

from sim.drivers.matlab import MatlabDriver

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "matlab"


class TestMatlabDetect:
    def test_detects_m_script(self):
        driver = MatlabDriver()
        assert driver.detect(FIXTURES / "matlab_ok.m") is True

    def test_detects_slx_model(self):
        driver = MatlabDriver()
        assert driver.detect(FIXTURES / "empty_model.slx") is True

    def test_detects_mdl_model(self):
        driver = MatlabDriver()
        assert driver.detect(FIXTURES / "empty_model.mdl") is True

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

    def test_slx_dispatches_via_sim_shim(self, monkeypatch, tmp_path):
        """Issue #27 Phase A: `.slx` routes through load_system → sim_shim.run
        → close_system, not through `run('...')`."""
        monkeypatch.setattr(
            "sim.drivers.matlab.driver.shutil.which",
            lambda _: "/usr/local/bin/matlab",
        )

        recorded = {}

        def fake_run(command, capture_output, text):
            recorded["command"] = command
            return SimpleNamespace(
                returncode=0,
                stdout='{"ok":true,"result_file":"/tmp/out.parquet","format":"parquet","signals":[]}\n',
                stderr="",
            )

        monkeypatch.setattr("sim.runner.subprocess.run", fake_run)

        model = tmp_path / "rc_circuit.slx"
        model.touch()

        driver = MatlabDriver()
        result = driver.run_file(model)

        assert result.exit_code == 0
        expr = recorded["command"][2]
        assert "load_system(" in expr
        assert "sim_shim.run(" in expr
        assert "close_system(" in expr
        assert "addpath(" in expr
        assert "rc_circuit" in expr
        # Does not fall back to the `.m` top-level `run('...')` wrapper
        assert not expr.startswith("run('")
        # Regression: MATLAB silently refuses to put a folder named
        # `resources` on the path (reserved name alongside `private`
        # and `@<class>`). The shim package parent must use a
        # non-reserved name, otherwise `which('sim_shim.run')` returns
        # empty inside MATLAB and dispatch fails with
        # "Unable to resolve the name 'sim_shim.run'." See PR fixing
        # the reserved-name bug discovered on win1.
        assert "/resources'" not in expr
        assert "matlab_pkg" in expr


class TestSimulinkLint:
    def test_slx_lint_is_info_only(self):
        driver = MatlabDriver()
        result = driver.lint(FIXTURES / "empty_model.slx")
        assert result.ok is True
        assert result.diagnostics
        assert result.diagnostics[0].level == "info"


class TestSimulinkProbe:
    def test_simulink_flag_populated_from_filesystem(self, tmp_path, monkeypatch):
        """detect_installed() should set extra.simulink_installed based on
        whether toolbox/simulink/simulink exists under the MATLAB root."""
        from sim.drivers.matlab import driver as drv

        matlab_root = tmp_path / "R2024a"
        (matlab_root / "bin").mkdir(parents=True)
        (matlab_root / "bin" / "matlab").write_text("#!/bin/sh\n")
        (matlab_root / "toolbox" / "simulink" / "simulink").mkdir(parents=True)

        monkeypatch.setattr(
            drv, "_INSTALL_FINDERS",
            [lambda: [(matlab_root / "bin" / "matlab", "test:synth")]],
        )

        installs = drv._scan_matlab_installs()
        assert len(installs) == 1
        assert installs[0].extra["simulink_installed"] is True

    def test_simulink_flag_false_when_toolbox_missing(self, tmp_path, monkeypatch):
        from sim.drivers.matlab import driver as drv

        matlab_root = tmp_path / "R2024a"
        (matlab_root / "bin").mkdir(parents=True)
        (matlab_root / "bin" / "matlab").write_text("#!/bin/sh\n")
        # No toolbox/simulink/

        monkeypatch.setattr(
            drv, "_INSTALL_FINDERS",
            [lambda: [(matlab_root / "bin" / "matlab", "test:synth")]],
        )

        installs = drv._scan_matlab_installs()
        assert len(installs) == 1
        assert installs[0].extra["simulink_installed"] is False


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
