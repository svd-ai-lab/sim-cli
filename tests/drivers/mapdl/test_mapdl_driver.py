"""Unit tests for MAPDL driver — 5-tier TDD pyramid.

Tier 1 (detect), Tier 2 (lint), Tier 3 (connect), Tier 4 (parse_output).
No real MAPDL launch — that lives in test_mapdl_e2e.py.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from sim.drivers.mapdl import MapdlDriver

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "mapdl"


@pytest.fixture
def driver():
    return MapdlDriver()


# ---------------------------------------------------------------------------
# Tier 1 — detect()
# ---------------------------------------------------------------------------

class TestDetect:
    def test_detect_good_script(self, driver):
        assert driver.detect(FIXTURES / "mapdl_good.py") is True

    def test_detect_unrelated_script(self, driver):
        assert driver.detect(FIXTURES / "mapdl_no_import.py") is False

    def test_detect_missing_file(self, driver, tmp_path):
        assert driver.detect(tmp_path / "does_not_exist.py") is False

    def test_detect_raw_apdl_is_not_mapdl_py(self, driver):
        # An APDL card file mislabelled as .py is not a PyMAPDL script.
        assert driver.detect(FIXTURES / "mapdl_raw_apdl.py") is False


# ---------------------------------------------------------------------------
# Tier 2 — lint()
# ---------------------------------------------------------------------------

class TestLint:
    def test_lint_good_script(self, driver):
        result = driver.lint(FIXTURES / "mapdl_good.py")
        assert result.ok is True
        # May have 0 diagnostics, or 0 errors at most
        assert all(d.level != "error" for d in result.diagnostics)

    def test_lint_syntax_error(self, driver):
        result = driver.lint(FIXTURES / "mapdl_syntax_error.py")
        assert result.ok is False
        assert any("Syntax error" in d.message for d in result.diagnostics)

    def test_lint_missing_import(self, driver):
        result = driver.lint(FIXTURES / "mapdl_no_import.py")
        assert result.ok is False
        assert any("ansys.mapdl.core" in d.message for d in result.diagnostics)

    def test_lint_raw_apdl_diagnoses(self, driver):
        result = driver.lint(FIXTURES / "mapdl_raw_apdl.py")
        assert result.ok is False
        # Either APDL-card hint or plain syntax error is acceptable —
        # both signal the same underlying mistake.
        messages = " ".join(d.message for d in result.diagnostics)
        assert "APDL" in messages or "Syntax error" in messages

    def test_lint_no_launch_warns(self, driver):
        result = driver.lint(FIXTURES / "mapdl_no_launch.py")
        # Import present, no launch — warning but not error
        assert result.ok is True
        assert any(
            d.level == "warning" and "launch_mapdl" in d.message
            for d in result.diagnostics
        )


# ---------------------------------------------------------------------------
# Tier 3 — connect() / detect_installed()
# ---------------------------------------------------------------------------

class TestConnect:
    def test_connect_returns_status(self, driver):
        info = driver.connect()
        # Either "ok" (local MAPDL found) or "not_installed" — both valid.
        assert info.status in ("ok", "not_installed")
        assert info.solver == "mapdl"

    def test_detect_installed_returns_list(self, driver):
        installs = driver.detect_installed()
        assert isinstance(installs, list)
        for inst in installs:
            assert inst.name == "mapdl"
            assert inst.version  # e.g. "24.1"


# ---------------------------------------------------------------------------
# Tier 4 — parse_output()
# ---------------------------------------------------------------------------

class TestParseOutput:
    def test_last_json_line(self, driver):
        stdout = 'log line 1\nlog line 2\n{"disp_max": 0.123, "stress_max": 1e6}\n'
        parsed = driver.parse_output(stdout)
        assert parsed == {"disp_max": 0.123, "stress_max": 1e6}

    def test_no_json_returns_empty(self, driver):
        assert driver.parse_output("just some text\nmore text\n") == {}

    def test_ignores_non_json_braces(self, driver):
        stdout = "{malformed\n{\"ok\": true}\n"
        assert driver.parse_output(stdout) == {"ok": True}


# ---------------------------------------------------------------------------
# Tier 5 — registry wiring
# ---------------------------------------------------------------------------

def test_driver_registered():
    from sim.drivers import get_driver
    d = get_driver("mapdl")
    assert d is not None
    assert d.name == "mapdl"
