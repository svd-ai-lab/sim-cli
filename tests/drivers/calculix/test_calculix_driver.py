"""Tier 1 protocol-compliance tests for the CalculiX driver."""
from __future__ import annotations

from pathlib import Path

import pytest

from sim.drivers.calculix import CalculixDriver

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"


class TestDetect:
    def setup_method(self):
        self.driver = CalculixDriver()

    def test_detect_good_inp(self):
        assert self.driver.detect(FIXTURES / "calculix_good.inp") is True

    def test_detect_no_keyword_inp(self):
        assert self.driver.detect(FIXTURES / "calculix_no_keyword.inp") is False

    def test_detect_non_inp_file(self):
        assert self.driver.detect(FIXTURES / "not_simulation.py") is False

    def test_detect_missing_file(self):
        assert self.driver.detect(Path("/does/not/exist.inp")) is False


class TestLint:
    def setup_method(self):
        self.driver = CalculixDriver()

    def test_lint_good_inp(self):
        result = self.driver.lint(FIXTURES / "calculix_good.inp")
        assert result.ok is True
        assert len([d for d in result.diagnostics if d.level == "error"]) == 0

    def test_lint_no_step_is_warning(self):
        result = self.driver.lint(FIXTURES / "calculix_no_step.inp")
        assert result.ok is True
        assert any(d.level == "warning" for d in result.diagnostics)

    def test_lint_no_keyword_is_error(self):
        result = self.driver.lint(FIXTURES / "calculix_no_keyword.inp")
        assert result.ok is False
        assert any(d.level == "error" for d in result.diagnostics)

    def test_lint_unsupported_suffix(self):
        result = self.driver.lint(FIXTURES / "not_simulation.py")
        assert result.ok is False


class TestConnect:
    def test_connect_not_installed(self, monkeypatch):
        driver = CalculixDriver()
        monkeypatch.setattr(driver, "detect_installed", lambda: [])
        info = driver.connect()
        assert info.status == "not_installed"

    def test_connect_found(self, monkeypatch):
        from sim.driver import SolverInstall
        driver = CalculixDriver()
        monkeypatch.setattr(
            driver, "detect_installed",
            lambda: [SolverInstall(
                name="calculix", version="2.11",
                path="/data/Chenyx/sim/opt/calculix/usr/bin",
                source="test",
                extra={"bin": "/data/Chenyx/sim/opt/calculix/usr/bin/ccx"},
            )],
        )
        info = driver.connect()
        assert info.status == "ok"
        assert info.version is not None


class TestParseOutput:
    def setup_method(self):
        self.driver = CalculixDriver()

    def test_last_json_line(self):
        stdout = 'Job finished\n{"tip_disp_m": 1.23e-5}\n'
        assert self.driver.parse_output(stdout) == {"tip_disp_m": 1.23e-5}

    def test_no_json(self):
        assert self.driver.parse_output("no json here") == {}

    def test_multiple_json_takes_last(self):
        stdout = '{"a": 1}\nlog\n{"b": 2}\n'
        assert self.driver.parse_output(stdout) == {"b": 2}


class TestRunFile:
    def test_raises_when_not_installed(self, monkeypatch):
        driver = CalculixDriver()
        monkeypatch.setattr(driver, "detect_installed", lambda: [])
        with pytest.raises(RuntimeError, match="(?i)calculix"):
            driver.run_file(FIXTURES / "calculix_good.inp")
