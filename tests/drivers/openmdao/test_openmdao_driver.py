"""Tier 1 protocol-compliance tests for the OpenMDAO driver."""
from __future__ import annotations

from pathlib import Path

import pytest

from sim.drivers.openmdao import OpenMDAODriver

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"


class TestDetect:
    def setup_method(self):
        self.driver = OpenMDAODriver()

    def test_good(self):
        assert self.driver.detect(FIXTURES / "openmdao_good.py") is True

    def test_no_import(self):
        assert self.driver.detect(FIXTURES / "openmdao_no_import.py") is False

    def test_wrong_suffix(self):
        assert self.driver.detect(FIXTURES / "not_simulation.py") is False

    def test_missing(self):
        assert self.driver.detect(Path("/no/such.py")) is False


class TestLint:
    def setup_method(self):
        self.driver = OpenMDAODriver()

    def test_good(self):
        assert self.driver.lint(FIXTURES / "openmdao_good.py").ok is True

    def test_no_import_error(self):
        assert self.driver.lint(FIXTURES / "openmdao_no_import.py").ok is False

    def test_no_usage_warn(self):
        r = self.driver.lint(FIXTURES / "openmdao_no_usage.py")
        assert r.ok is True
        assert any(d.level == "warning" for d in r.diagnostics)

    def test_syntax_error(self):
        assert self.driver.lint(FIXTURES / "openmdao_syntax_error.py").ok is False

    def test_wrong_suffix(self):
        import os, tempfile
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            p = Path(f.name)
        try:
            assert self.driver.lint(p).ok is False
        finally:
            os.unlink(p)


class TestConnect:
    def test_not_installed(self, monkeypatch):
        d = OpenMDAODriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [])
        assert d.connect().status == "not_installed"

    def test_found(self, monkeypatch):
        from sim.driver import SolverInstall
        d = OpenMDAODriver()
        monkeypatch.setattr(
            d, "detect_installed",
            lambda: [SolverInstall(
                name="openmdao", version="3.30", path="/x", source="test",
                extra={"python": "/x/python", "raw_version": "3.30.0"},
            )],
        )
        assert d.connect().status == "ok"


class TestParseOutput:
    def setup_method(self):
        self.driver = OpenMDAODriver()

    def test_last_json(self):
        stdout = 'NL: NLBGS Converged in 8 iterations\n{"y1": 25.59}\n'
        assert self.driver.parse_output(stdout)["y1"] == 25.59


class TestRunFile:
    def test_raises_when_not_installed(self, monkeypatch):
        d = OpenMDAODriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [])
        with pytest.raises(RuntimeError, match="(?i)openmdao"):
            d.run_file(FIXTURES / "openmdao_good.py")

    def test_wrong_suffix(self, monkeypatch):
        from sim.driver import SolverInstall
        d = OpenMDAODriver()
        monkeypatch.setattr(
            d, "detect_installed",
            lambda: [SolverInstall(
                name="openmdao", version="3.30", path="/x", source="test",
                extra={"python": "/x/python"},
            )],
        )
        import os, tempfile
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            p = Path(f.name)
        try:
            with pytest.raises(RuntimeError, match="(?i)openmdao"):
                d.run_file(p)
        finally:
            os.unlink(p)
