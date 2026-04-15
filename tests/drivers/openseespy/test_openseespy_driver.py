"""Tier 1 protocol-compliance tests for the OpenSeesPy driver."""
from __future__ import annotations

from pathlib import Path

import pytest

from sim.drivers.openseespy import OpenSeesPyDriver

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"


class TestDetect:
    def setup_method(self):
        self.driver = OpenSeesPyDriver()

    def test_good(self):
        assert self.driver.detect(FIXTURES / "openseespy_good.py") is True

    def test_no_import(self):
        assert self.driver.detect(FIXTURES / "openseespy_no_import.py") is False

    def test_wrong_suffix(self):
        assert self.driver.detect(FIXTURES / "not_simulation.py") is False

    def test_missing(self):
        assert self.driver.detect(Path("/no/such.py")) is False


class TestLint:
    def setup_method(self):
        self.driver = OpenSeesPyDriver()

    def test_good(self):
        assert self.driver.lint(FIXTURES / "openseespy_good.py").ok is True

    def test_no_import_error(self):
        assert self.driver.lint(FIXTURES / "openseespy_no_import.py").ok is False

    def test_no_usage_warn(self):
        r = self.driver.lint(FIXTURES / "openseespy_no_model.py")
        assert r.ok is True
        assert any(d.level == "warning" for d in r.diagnostics)

    def test_syntax_error(self):
        assert self.driver.lint(FIXTURES / "openseespy_syntax_error.py").ok is False

    def test_wrong_suffix(self):
        import os
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            p = Path(f.name)
        try:
            assert self.driver.lint(p).ok is False
        finally:
            os.unlink(p)


class TestConnect:
    def test_not_installed(self, monkeypatch):
        d = OpenSeesPyDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [])
        assert d.connect().status == "not_installed"

    def test_found(self, monkeypatch):
        from sim.driver import SolverInstall
        d = OpenSeesPyDriver()
        monkeypatch.setattr(
            d, "detect_installed",
            lambda: [SolverInstall(
                name="openseespy", version="3.5", path="/x", source="test",
                extra={"python": "/x/python", "raw_version": "3.5.1.3"},
            )],
        )
        assert d.connect().status == "ok"


class TestParseOutput:
    def setup_method(self):
        self.driver = OpenSeesPyDriver()

    def test_last_json(self):
        stdout = 'banner\nProcess 0 Terminating\n{"disp": -0.123}\n'
        assert self.driver.parse_output(stdout)["disp"] == -0.123

    def test_no_json(self):
        assert self.driver.parse_output("Process 0 Terminating\n") == {}


class TestRunFile:
    def test_raises_when_not_installed(self, monkeypatch):
        d = OpenSeesPyDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [])
        with pytest.raises(RuntimeError, match="(?i)openseespy"):
            d.run_file(FIXTURES / "openseespy_good.py")

    def test_wrong_suffix(self, monkeypatch):
        from sim.driver import SolverInstall
        d = OpenSeesPyDriver()
        monkeypatch.setattr(
            d, "detect_installed",
            lambda: [SolverInstall(
                name="openseespy", version="3.5", path="/x", source="test",
                extra={"python": "/x/python"},
            )],
        )
        import os
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            p = Path(f.name)
        try:
            with pytest.raises(RuntimeError, match="(?i)openseespy"):
                d.run_file(p)
        finally:
            os.unlink(p)
