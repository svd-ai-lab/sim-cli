"""Tier 1 protocol-compliance tests for the LAMMPS driver."""
from __future__ import annotations

from pathlib import Path

import pytest

from sim.drivers.lammps import LammpsDriver

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"


class TestDetect:
    def setup_method(self):
        self.driver = LammpsDriver()

    def test_detect_good_in(self):
        assert self.driver.detect(FIXTURES / "lammps_good.in") is True

    def test_detect_not_lammps_content(self):
        assert self.driver.detect(FIXTURES / "lammps_not_input.in") is False

    def test_detect_unsupported_suffix(self):
        assert self.driver.detect(FIXTURES / "not_simulation.py") is False

    def test_detect_missing_file(self):
        assert self.driver.detect(Path("/does/not/exist.in")) is False


class TestLint:
    def setup_method(self):
        self.driver = LammpsDriver()

    def test_lint_good_in(self):
        r = self.driver.lint(FIXTURES / "lammps_good.in")
        assert r.ok is True

    def test_lint_missing_units_is_error(self):
        r = self.driver.lint(FIXTURES / "lammps_no_units.in")
        assert r.ok is False
        assert any(d.level == "error" and "units" in d.message.lower()
                   for d in r.diagnostics)

    def test_lint_no_run_is_warning(self):
        r = self.driver.lint(FIXTURES / "lammps_no_run.in")
        assert r.ok is True  # warning doesn't fail
        assert any(d.level == "warning" for d in r.diagnostics)

    def test_lint_unsupported_suffix(self):
        r = self.driver.lint(FIXTURES / "not_simulation.py")
        assert r.ok is False


class TestConnect:
    def test_connect_not_installed(self, monkeypatch):
        driver = LammpsDriver()
        monkeypatch.setattr(driver, "detect_installed", lambda: [])
        info = driver.connect()
        assert info.status == "not_installed"

    def test_connect_found(self, monkeypatch):
        from sim.driver import SolverInstall
        driver = LammpsDriver()
        monkeypatch.setattr(
            driver, "detect_installed",
            lambda: [SolverInstall(
                name="lammps", version="20230824",
                path="/fake/bin", source="test",
                extra={"bin": "/fake/bin/lmp", "raw_version": "24 Aug 2023"},
            )],
        )
        info = driver.connect()
        assert info.status == "ok"


class TestParseOutput:
    def setup_method(self):
        self.driver = LammpsDriver()

    def test_last_json_line(self):
        stdout = 'Total wall time: 0:00:03\n{"final_temp": 1.47, "steps": 50}\n'
        assert self.driver.parse_output(stdout) == {"final_temp": 1.47, "steps": 50}

    def test_no_json(self):
        assert self.driver.parse_output("Total wall time: 0:00:03") == {}


class TestRunFile:
    def test_raises_when_not_installed(self, monkeypatch):
        driver = LammpsDriver()
        monkeypatch.setattr(driver, "detect_installed", lambda: [])
        with pytest.raises(RuntimeError, match="(?i)lammps"):
            driver.run_file(FIXTURES / "lammps_good.in")

    def test_rejects_unsupported_suffix(self, monkeypatch):
        from sim.driver import SolverInstall
        driver = LammpsDriver()
        monkeypatch.setattr(
            driver, "detect_installed",
            lambda: [SolverInstall(
                name="lammps", version="2023", path="/x", source="test",
                extra={"bin": "/x/lmp"},
            )],
        )
        with pytest.raises(RuntimeError, match="(?i)lammps"):
            driver.run_file(FIXTURES / "not_simulation.py")
