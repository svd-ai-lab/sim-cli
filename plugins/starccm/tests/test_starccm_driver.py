"""Tier 1 protocol-compliance tests for the STAR-CCM+ driver."""
from __future__ import annotations

from pathlib import Path

import pytest

from sim_plugin_starccm import StarccmDriver

FIXTURES = Path(__file__).parent.parent / "fixtures"


class TestDetect:
    """detect() recognizes STAR-CCM+ Java macros."""

    @pytest.fixture(autouse=True)
    def _driver(self):
        self.driver = StarccmDriver()

    def test_detect_good_macro(self):
        assert self.driver.detect(FIXTURES / "starccm_good.java") is True

    def test_detect_no_star_macro(self):
        assert self.driver.detect(FIXTURES / "starccm_no_star_macro.java") is False

    def test_detect_python_script(self):
        # A non-Java file must not be claimed by the STAR-CCM+ driver.
        assert self.driver.detect(FIXTURES / "not_a_macro.py") is False

    def test_detect_missing_file(self):
        assert self.driver.detect(FIXTURES / "nonexistent.java") is False


class TestLint:
    """lint() validates STAR-CCM+ macro structure."""

    @pytest.fixture(autouse=True)
    def _driver(self):
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
    """detect_installed() finds STAR-CCM+ binaries."""

    @pytest.fixture(autouse=True)
    def _driver(self):
        self.driver = StarccmDriver()

    def test_detect_installed_returns_list(self):
        installs = self.driver.detect_installed()
        assert isinstance(installs, list)
        # On a host with STAR-CCM+ installed, should find at least one.
        # On CI without STAR-CCM+, should return an empty list.

    def test_detect_installed_no_duplicates(self):
        installs = self.driver.detect_installed()
        paths = [i.path for i in installs]
        assert len(paths) == len(set(paths))
