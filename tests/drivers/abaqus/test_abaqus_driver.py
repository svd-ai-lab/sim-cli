"""Tier 1 protocol-compliance tests for the Abaqus driver."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sim.drivers.abaqus import AbaqusDriver

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "abaqus"


class TestDetect:
    def setup_method(self):
        self.driver = AbaqusDriver()

    def test_detect_good_py_script(self):
        """Python script with Abaqus import -> True."""
        assert self.driver.detect(FIXTURES / "abaqus_good.py") is True

    def test_detect_good_inp_file(self):
        """Abaqus .inp input deck -> True."""
        assert self.driver.detect(FIXTURES / "abaqus_inp_good.inp") is True

    def test_detect_unrelated_script(self):
        """Script without Abaqus import -> False."""
        assert self.driver.detect(FIXTURES.parent / "not_simulation.py") is False

    def test_detect_no_import_py(self):
        """Python without Abaqus import -> False."""
        assert self.driver.detect(FIXTURES / "abaqus_no_import.py") is False

    def test_detect_missing_file(self):
        """Non-existent path -> False (no exception)."""
        assert self.driver.detect(Path("/does/not/exist.py")) is False

    def test_detect_syntax_error_still_detects(self):
        """Regex-based detection works even on broken syntax."""
        assert self.driver.detect(FIXTURES / "abaqus_syntax_error.py") is True


class TestLint:
    def setup_method(self):
        self.driver = AbaqusDriver()

    def test_lint_good_py(self):
        result = self.driver.lint(FIXTURES / "abaqus_good.py")
        assert result.ok is True
        assert len([d for d in result.diagnostics if d.level == "error"]) == 0

    def test_lint_good_inp(self):
        result = self.driver.lint(FIXTURES / "abaqus_inp_good.inp")
        assert result.ok is True

    def test_lint_bad_syntax(self):
        result = self.driver.lint(FIXTURES / "abaqus_syntax_error.py")
        assert result.ok is False
        assert any(
            d.level == "error" and "syntax" in d.message.lower()
            for d in result.diagnostics
        )

    def test_lint_missing_import(self):
        result = self.driver.lint(FIXTURES / "abaqus_no_import.py")
        assert result.ok is False
        assert any(
            "import" in d.message.lower()
            for d in result.diagnostics
            if d.level == "error"
        )

    def test_lint_no_step_is_warning(self):
        """Input deck without *STEP -> warning, not error."""
        result = self.driver.lint(FIXTURES / "abaqus_no_step.inp")
        assert result.ok is True
        assert any(d.level == "warning" for d in result.diagnostics)


class TestConnect:
    def test_connect_not_installed(self, monkeypatch):
        """When abaqus not found -> status='not_installed'."""
        driver = AbaqusDriver()
        monkeypatch.setattr(driver, "detect_installed", lambda: [])
        info = driver.connect()
        assert info.status == "not_installed"

    def test_connect_found(self, monkeypatch):
        """When abaqus found -> status='ok', version populated."""
        from sim.driver import SolverInstall

        driver = AbaqusDriver()
        monkeypatch.setattr(
            driver,
            "detect_installed",
            lambda: [
                SolverInstall(
                    name="abaqus",
                    version="2026",
                    path="C:/SIMULIA",
                    source="test",
                )
            ],
        )
        info = driver.connect()
        assert info.status == "ok"
        assert info.version is not None


class TestParseOutput:
    def setup_method(self):
        self.driver = AbaqusDriver()

    def test_last_json_line(self):
        stdout = 'Abaqus JOB log output\n{"displacement": 0.0123}\n'
        result = self.driver.parse_output(stdout)
        assert result == {"displacement": 0.0123}

    def test_no_json(self):
        result = self.driver.parse_output("just plain solver output\n")
        assert result == {}

    def test_multiple_json_takes_last(self):
        stdout = '{"a": 1}\nsome log\n{"b": 2}\n'
        result = self.driver.parse_output(stdout)
        assert result == {"b": 2}

    def test_invalid_json_skipped(self):
        stdout = '{broken\n{"valid": true}\n'
        result = self.driver.parse_output(stdout)
        assert result == {"valid": True}


class TestRunFile:
    def test_raises_when_not_installed(self, monkeypatch):
        driver = AbaqusDriver()
        monkeypatch.setattr(driver, "detect_installed", lambda: [])
        with pytest.raises(RuntimeError, match="(?i)abaqus"):
            driver.run_file(FIXTURES / "abaqus_good.py")
