"""Unit tests for ICEM CFD driver — 5-tier TDD pyramid."""
from __future__ import annotations

from pathlib import Path

import pytest

from sim.drivers.icem import IcemDriver

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "icem"


@pytest.fixture
def driver():
    return IcemDriver()


# ---------------------------------------------------------------------------
# Tier 1 — detect()
# ---------------------------------------------------------------------------

class TestDetect:
    def test_detect_good_tcl(self, driver):
        assert driver.detect(FIXTURES / "icem_good.tcl") is True

    def test_detect_no_markers(self, driver):
        assert driver.detect(FIXTURES / "icem_no_markers.tcl") is False

    def test_detect_wrong_extension(self, driver):
        assert driver.detect(FIXTURES / "not_tcl.py") is False

    def test_detect_missing_file(self, driver, tmp_path):
        assert driver.detect(tmp_path / "gone.tcl") is False

    def test_detect_bad_braces_still_detected(self, driver):
        # Has ic_ markers — detection succeeds (lint catches the brace issue)
        assert driver.detect(FIXTURES / "icem_bad_braces.tcl") is True


# ---------------------------------------------------------------------------
# Tier 2 — lint()
# ---------------------------------------------------------------------------

class TestLint:
    def test_lint_good_script(self, driver):
        result = driver.lint(FIXTURES / "icem_good.tcl")
        assert result.ok is True

    def test_lint_no_markers(self, driver):
        result = driver.lint(FIXTURES / "icem_no_markers.tcl")
        assert result.ok is False
        assert any("ic_*" in d.message or "ICEM" in d.message for d in result.diagnostics)

    def test_lint_bad_braces(self, driver):
        result = driver.lint(FIXTURES / "icem_bad_braces.tcl")
        assert result.ok is False
        assert any("brace" in d.message.lower() for d in result.diagnostics)

    def test_lint_missing_file(self, driver, tmp_path):
        result = driver.lint(tmp_path / "no.tcl")
        assert result.ok is False

    def test_lint_wrong_extension_warns(self, driver, tmp_path):
        # .xyz extension with ic_ commands → ok=True but warning
        f = tmp_path / "mesh.xyz"
        f.write_text("ic_load_tetin test.tin\n", encoding="utf-8")
        result = driver.lint(f)
        # wrong extension but has markers — should still pass (detect checks ext, lint is lenient)
        # Actually lint also warns about extension
        assert any("extension" in d.message.lower() for d in result.diagnostics)


# ---------------------------------------------------------------------------
# Tier 3 — connect() / detect_installed()
# ---------------------------------------------------------------------------

class TestConnect:
    def test_connect_returns_status(self, driver):
        info = driver.connect()
        assert info.status in ("ok", "not_installed")
        assert info.solver == "icem"

    def test_detect_installed_returns_list(self, driver):
        installs = driver.detect_installed()
        assert isinstance(installs, list)
        for inst in installs:
            assert inst.name == "icem"


# ---------------------------------------------------------------------------
# Tier 4 — parse_output()
# ---------------------------------------------------------------------------

class TestParseOutput:
    def test_last_json_line(self, driver):
        stdout = 'ICEM meshing log\n{"nodes": 1234, "elements": 5678}\n'
        assert driver.parse_output(stdout) == {"nodes": 1234, "elements": 5678}

    def test_no_json(self, driver):
        assert driver.parse_output("just text\n") == {}


# ---------------------------------------------------------------------------
# Tier 5 — registry wiring
# ---------------------------------------------------------------------------

def test_driver_registered():
    from sim.drivers import get_driver
    d = get_driver("icem")
    assert d is not None
    assert d.name == "icem"
