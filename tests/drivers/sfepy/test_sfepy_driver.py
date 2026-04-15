"""Tier 1 protocol-compliance tests for the SfePy driver."""
from __future__ import annotations

from pathlib import Path

import pytest

from sim.drivers.sfepy import SfepyDriver

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"


class TestDetect:
    def setup_method(self):
        self.driver = SfepyDriver()

    def test_good(self):
        assert self.driver.detect(FIXTURES / "sfepy_good.py") is True

    def test_no_import(self):
        assert self.driver.detect(FIXTURES / "sfepy_no_import.py") is False

    def test_wrong_suffix(self):
        assert self.driver.detect(FIXTURES / "not_simulation.py") is False

    def test_missing(self):
        assert self.driver.detect(Path("/no/such.py")) is False


class TestLint:
    def setup_method(self):
        self.driver = SfepyDriver()

    def test_good(self):
        assert self.driver.lint(FIXTURES / "sfepy_good.py").ok is True

    def test_no_import_error(self):
        assert self.driver.lint(FIXTURES / "sfepy_no_import.py").ok is False

    def test_no_usage_warn(self):
        r = self.driver.lint(FIXTURES / "sfepy_no_usage.py")
        assert r.ok is True
        assert any(d.level == "warning" for d in r.diagnostics)

    def test_syntax_error(self):
        assert self.driver.lint(FIXTURES / "sfepy_syntax_error.py").ok is False

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
        d = SfepyDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [])
        assert d.connect().status == "not_installed"

    def test_found(self, monkeypatch):
        from sim.driver import SolverInstall
        d = SfepyDriver()
        monkeypatch.setattr(
            d, "detect_installed",
            lambda: [SolverInstall(
                name="sfepy", version="2025.4", path="/x", source="test",
                extra={"python": "/x/python", "raw_version": "2025.4"},
            )],
        )
        assert d.connect().status == "ok"


class TestParseOutput:
    def setup_method(self):
        self.driver = SfepyDriver()

    def test_last_json(self):
        stdout = 'sfepy: solving...\n{"u_max": 0.0746, "n_dofs": 81}\n'
        assert self.driver.parse_output(stdout)["n_dofs"] == 81

    def test_no_json(self):
        assert self.driver.parse_output("nothing\n") == {}


class TestRunFile:
    def test_raises_when_not_installed(self, monkeypatch):
        d = SfepyDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [])
        with pytest.raises(RuntimeError, match="(?i)sfepy"):
            d.run_file(FIXTURES / "sfepy_good.py")

    def test_wrong_suffix(self, monkeypatch):
        from sim.driver import SolverInstall
        d = SfepyDriver()
        monkeypatch.setattr(
            d, "detect_installed",
            lambda: [SolverInstall(
                name="sfepy", version="2025.4", path="/x", source="test",
                extra={"python": "/x/python"},
            )],
        )
        import os
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            p = Path(f.name)
        try:
            with pytest.raises(RuntimeError, match="(?i)sfepy"):
                d.run_file(p)
        finally:
            os.unlink(p)
