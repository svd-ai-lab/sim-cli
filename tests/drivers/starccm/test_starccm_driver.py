"""Star-CCM+ driver unit tests — TDD RED phase."""
from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "starccm"


class TestDetect:
    """detect() recognizes Star-CCM+ Java macros."""

    @pytest.fixture(autouse=True)
    def _driver(self):
        from sim.drivers.starccm import StarccmDriver
        self.driver = StarccmDriver()

    def test_detect_good_macro(self):
        assert self.driver.detect(FIXTURES / "starccm_good.java") is True

    def test_detect_no_star_macro(self):
        assert self.driver.detect(FIXTURES / "starccm_no_star_macro.java") is False

    def test_detect_python_script(self):
        pybamm_fixtures = FIXTURES.parent / "pybamm"
        assert self.driver.detect(pybamm_fixtures / "pybamm_spm_good.py") is False

    def test_detect_missing_file(self):
        assert self.driver.detect(FIXTURES / "nonexistent.java") is False


class TestLint:
    """lint() validates Star-CCM+ macro structure."""

    @pytest.fixture(autouse=True)
    def _driver(self):
        from sim.drivers.starccm import StarccmDriver
        self.driver = StarccmDriver()

    def test_lint_good_macro(self):
        result = self.driver.lint(FIXTURES / "starccm_good.java")
        assert result.ok is True

    def test_lint_no_star_macro(self):
        result = self.driver.lint(FIXTURES / "starccm_no_star_macro.java")
        assert result.ok is False
        assert any("StarMacro" in d.message for d in result.diagnostics)

    def test_lint_no_get_simulation(self):
        result = self.driver.lint(FIXTURES / "starccm_no_get_sim.java")
        assert result.ok is True  # warning only, not an error
        assert any("getActiveSimulation" in d.message for d in result.diagnostics)


class TestConnect:
    """connect() reports availability."""

    @pytest.fixture(autouse=True)
    def _driver(self):
        from sim.drivers.starccm import StarccmDriver
        self.driver = StarccmDriver()

    def test_connect_returns_connection_info(self):
        info = self.driver.connect()
        assert info.solver == "starccm"
        # May be "ok" or "not_installed" depending on host
        assert info.status in ("ok", "not_installed")


class TestParseOutput:
    """parse_output() extracts last JSON line."""

    @pytest.fixture(autouse=True)
    def _driver(self):
        from sim.drivers.starccm import StarccmDriver
        self.driver = StarccmDriver()

    def test_last_json_line(self):
        stdout = 'Loading...\nStarting...\n{"ok": true, "cells": 1000}'
        result = self.driver.parse_output(stdout)
        assert result == {"ok": True, "cells": 1000}

    def test_no_json(self):
        result = self.driver.parse_output("Just some text\nNo json here")
        assert result == {}

    def test_empty_stdout(self):
        result = self.driver.parse_output("")
        assert result == {}


class TestDetectInstalled:
    """detect_installed() finds Star-CCM+ binaries."""

    @pytest.fixture(autouse=True)
    def _driver(self):
        from sim.drivers.starccm import StarccmDriver
        self.driver = StarccmDriver()

    def test_detect_installed_returns_list(self):
        installs = self.driver.detect_installed()
        assert isinstance(installs, list)
        # On this machine with Star-CCM+ installed, should find at least one
        # On CI without Star-CCM+, should return empty list

    def test_detect_installed_no_duplicates(self):
        installs = self.driver.detect_installed()
        paths = [i.path for i in installs]
        assert len(paths) == len(set(paths))
