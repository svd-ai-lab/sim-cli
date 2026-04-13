"""Tier 1 + Tier 2 tests for the Ansys Workbench driver.

Tests run without a real Workbench installation — detection is monkeypatched.
Tier 4 (real solver) tests are in test_workbench_integration.py.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sim.driver import DriverProtocol, SolverInstall

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "workbench"


@pytest.fixture
def driver():
    from sim.drivers.workbench.driver import WorkbenchDriver
    return WorkbenchDriver()


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------

class TestProtocolCompliance:
    def test_is_protocol(self, driver):
        assert isinstance(driver, DriverProtocol)

    def test_name(self, driver):
        assert driver.name == "workbench"


# ---------------------------------------------------------------------------
# detect()
# ---------------------------------------------------------------------------

class TestDetect:
    def test_detect_wbjn_good(self, driver):
        assert driver.detect(FIXTURES / "workbench_good.wbjn") is True

    def test_detect_wbjn_no_marker(self, driver):
        assert driver.detect(FIXTURES / "workbench_no_marker.wbjn") is True

    def test_detect_py_with_wb_import(self, driver):
        assert driver.detect(FIXTURES / "workbench_py_good.py") is True

    def test_detect_unrelated_py(self, driver):
        assert driver.detect(FIXTURES.parent / "pybamm" / "pybamm_spm_good.py") is False

    def test_detect_missing_file(self, driver):
        assert driver.detect(FIXTURES / "nonexistent.wbjn") is False

    def test_detect_comsol(self, driver):
        assert driver.detect(FIXTURES.parent / "comsol" / "comsol_good.py") is False


# ---------------------------------------------------------------------------
# lint()
# ---------------------------------------------------------------------------

class TestLint:
    def test_lint_good_wbjn(self, driver):
        result = driver.lint(FIXTURES / "workbench_good.wbjn")
        assert result.ok is True

    def test_lint_bad_syntax(self, driver):
        result = driver.lint(FIXTURES / "workbench_bad_syntax.wbjn")
        assert result.ok is False
        assert any(d.level == "error" for d in result.diagnostics)

    def test_lint_no_marker(self, driver):
        result = driver.lint(FIXTURES / "workbench_no_marker.wbjn")
        assert result.ok is True
        assert any(d.level == "warning" for d in result.diagnostics)

    def test_lint_py_good(self, driver):
        result = driver.lint(FIXTURES / "workbench_py_good.py")
        assert result.ok is True


# ---------------------------------------------------------------------------
# connect()
# ---------------------------------------------------------------------------

class TestConnect:
    def test_connect_not_installed(self, driver, monkeypatch):
        monkeypatch.setattr(driver, "detect_installed", lambda: [])
        info = driver.connect()
        assert info.status == "not_installed"

    def test_connect_found(self, driver, monkeypatch):
        fake = [SolverInstall(
            name="workbench", version="24.1",
            path="C:/fake/ansys/v241", source="env:AWP_ROOT241",
        )]
        monkeypatch.setattr(driver, "detect_installed", lambda: fake)
        info = driver.connect()
        assert info.status == "ok"
        assert info.version == "24.1"

    def test_connect_message_shows_sdk_status(self, driver, monkeypatch):
        """Message should indicate whether SDK is available."""
        fake = [SolverInstall(
            name="workbench", version="24.1",
            path="C:/fake/v241", source="env:AWP_ROOT241",
        )]
        monkeypatch.setattr(driver, "detect_installed", lambda: fake)
        info = driver.connect()
        # Should mention either PyWorkbench version or RunWB2 fallback
        assert "PyWorkbench" in info.message or "RunWB2" in info.message


# ---------------------------------------------------------------------------
# parse_output()
# ---------------------------------------------------------------------------

class TestParseOutput:
    def test_last_json_line(self, driver):
        stdout = 'some log\n{"status": "done", "elapsed": 12.3}\ntrailer'
        assert driver.parse_output(stdout) == {"status": "done", "elapsed": 12.3}

    def test_no_json(self, driver):
        assert driver.parse_output("no json here\n") == {}

    def test_empty(self, driver):
        assert driver.parse_output("") == {}


# ---------------------------------------------------------------------------
# detect_installed()
# ---------------------------------------------------------------------------

class TestDetectInstalled:
    def test_returns_list(self, driver):
        assert isinstance(driver.detect_installed(), list)

    def test_env_var_detection(self, driver, monkeypatch):
        monkeypatch.setenv("AWP_ROOT241", "E:\\Program Files\\ANSYS Inc\\v241")
        result = driver.detect_installed()
        env_sources = [i for i in result if i.source.startswith("env:")]
        assert len(env_sources) >= 1
        assert env_sources[0].version == "24.1"

    def test_version_extraction(self, driver):
        assert driver._extract_version(Path("v241")) == "24.1"
        assert driver._extract_version(Path("v251")) == "25.1"
        assert driver._extract_version(Path("v232")) == "23.2"
        assert driver._extract_version(Path("some_random")) is None


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

class TestSessionLifecycle:
    def test_not_connected_initially(self, driver):
        assert driver.is_connected is False

    def test_disconnect_noop_when_not_connected(self, driver):
        driver.disconnect()
        assert driver.is_connected is False

    def test_run_raises_without_session(self, driver):
        with pytest.raises(RuntimeError, match="No active session"):
            driver.run("print('hello')")

    def test_query_raises_unknown(self, driver):
        with pytest.raises(ValueError, match="unknown query"):
            driver.query("nonexistent")


# ---------------------------------------------------------------------------
# Fallback logic
# ---------------------------------------------------------------------------

class TestFallback:
    """SDK failure should fall back to RunWB2."""

    def test_run_file_falls_back_when_sdk_import_fails(self, driver, monkeypatch):
        """If ansys.workbench.core can't be imported, fall back to RunWB2."""
        monkeypatch.setattr(
            "sim.drivers.workbench.driver._try_import_pyworkbench", lambda: None
        )
        monkeypatch.setattr(driver, "detect_installed", lambda: [
            SolverInstall(
                name="workbench", version="24.1",
                path="E:\\Program Files\\ANSYS Inc\\v241",
                source="env:AWP_ROOT241",
            ),
        ])
        # Fallback to RunWB2 should produce a RunResult with captured output.
        # workbench_good.wbjn has a known API error (GetModel not available),
        # so it should report as failed with errors captured.
        result = driver.run_file(FIXTURES / "workbench_good.wbjn")
        assert result.solver == "workbench"
        # The script has errors — verify the driver actually detected them
        assert not result.ok, f"Expected failure but got ok=True. stdout={result.stdout[:200]}, errors={result.errors}"

    def test_launch_falls_back_when_sdk_raises(self, driver, monkeypatch):
        """If SDK launch raises, fall back to RunWB2 session."""
        def _mock_pywb():
            class _FakeModule:
                __version__ = "0.0.0"
                @staticmethod
                def launch_workbench(**kwargs):
                    raise RuntimeError("SDK launch failed")
            return _FakeModule()

        monkeypatch.setattr(
            "sim.drivers.workbench.driver._try_import_pyworkbench", _mock_pywb
        )
        monkeypatch.setattr(driver, "detect_installed", lambda: [
            SolverInstall(
                name="workbench", version="24.1",
                path="E:\\Program Files\\ANSYS Inc\\v241",
                source="env:AWP_ROOT241",
            ),
        ])
        info = driver.launch(mode="workbench")
        assert info["ok"] is True
        assert info["backend"] == "runwb2"
        driver.disconnect()


# ---------------------------------------------------------------------------
# run_file()
# ---------------------------------------------------------------------------

class TestRunFile:
    def test_raises_when_not_installed(self, driver, monkeypatch):
        monkeypatch.setattr(driver, "detect_installed", lambda: [])
        with pytest.raises(RuntimeError, match="not found"):
            driver.run_file(FIXTURES / "workbench_good.wbjn")
