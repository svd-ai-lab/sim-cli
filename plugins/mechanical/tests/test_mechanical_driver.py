"""Tier 1 protocol-compliance tests for the Mechanical driver."""
from __future__ import annotations

from pathlib import Path

import pytest

from sim_plugin_mechanical import MechanicalDriver

FIXTURES = Path(__file__).parent.parent / "fixtures"


class TestDetect:
    def setup_method(self):
        self.driver = MechanicalDriver()

    def test_good_extapi(self):
        assert self.driver.detect(FIXTURES / "mechanical_good.py") is True

    def test_sdk_import(self):
        assert self.driver.detect(FIXTURES / "mechanical_sdk_import.py") is True

    def test_no_markers(self):
        assert self.driver.detect(FIXTURES / "mechanical_no_markers.py") is False

    def test_wrong_suffix(self):
        assert self.driver.detect(FIXTURES / "not_simulation.py") is False

    def test_missing(self):
        assert self.driver.detect(Path("/no/such.py")) is False


class TestLint:
    def setup_method(self):
        self.driver = MechanicalDriver()

    def test_good(self):
        assert self.driver.lint(FIXTURES / "mechanical_good.py").ok is True

    def test_sdk_import(self):
        assert self.driver.lint(FIXTURES / "mechanical_sdk_import.py").ok is True

    def test_no_markers_warn(self):
        r = self.driver.lint(FIXTURES / "mechanical_no_markers.py")
        assert r.ok is True
        assert any(d.level == "warning" for d in r.diagnostics)

    def test_syntax_error(self):
        assert self.driver.lint(FIXTURES / "mechanical_syntax_error.py").ok is False


class TestConnect:
    def test_not_installed(self, monkeypatch):
        d = MechanicalDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [])
        info = d.connect()
        assert info.status == "not_installed"

    def test_found_no_sdk(self, monkeypatch):
        from sim.driver import SolverInstall
        import sim_plugin_mechanical.driver as drv
        d = MechanicalDriver()
        monkeypatch.setattr(
            d, "detect_installed",
            lambda: [SolverInstall(
                name="mechanical", version="24.1",
                path="C:/Program Files/ANSYS Inc/v241",
                source="test",
                extra={"exe": "C:/Program Files/ANSYS Inc/v241/aisol/bin/winx64/AnsysWBU.exe"},
            )],
        )
        # Force PyMechanical missing.
        monkeypatch.setattr(drv, "_try_import_pymechanical", lambda: None)
        info = d.connect()
        assert info.status == "error"
        assert "ansys-mechanical-core" in info.message


class TestParseOutput:
    def setup_method(self):
        self.driver = MechanicalDriver()

    def test_last_json(self):
        stdout = 'banner\n{"n_analyses": 2, "ok": true}\n'
        out = self.driver.parse_output(stdout)
        assert out["n_analyses"] == 2
        assert out["ok"] is True

    def test_no_json(self):
        assert self.driver.parse_output("nope") == {}

    def test_empty(self):
        assert self.driver.parse_output("") == {}


class TestRunFile:
    def test_raises_when_not_installed(self, monkeypatch):
        d = MechanicalDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [])
        # If PyMechanical is not importable in the test env, the
        # _try_import_pymechanical guard fires first; if it is, the
        # detect_installed guard fires next. Either way the driver must
        # raise before contacting Mechanical.
        with pytest.raises(RuntimeError):
            d.run_file(FIXTURES / "mechanical_good.py")


class TestVersionCode:
    def test_version_code(self):
        from sim_plugin_mechanical.driver import _version_code
        assert _version_code("24.1") == 241
        assert _version_code("25.2") == 252


class TestExtractVersion:
    def test_extract(self):
        d = MechanicalDriver()
        assert d._extract_version(Path("v241")) == "24.1"
        assert d._extract_version(Path("v252")) == "25.2"
        assert d._extract_version(Path("not-a-version")) is None
