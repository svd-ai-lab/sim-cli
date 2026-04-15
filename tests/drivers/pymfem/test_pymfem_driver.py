"""Tier 1 protocol-compliance tests for the PyMFEM driver."""
from __future__ import annotations

from pathlib import Path

import pytest

from sim.drivers.pymfem import PymfemDriver

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"


class TestDetect:
    def setup_method(self):
        self.driver = PymfemDriver()

    def test_good(self):
        assert self.driver.detect(FIXTURES / "mfem_good.py") is True

    def test_no_import(self):
        assert self.driver.detect(FIXTURES / "mfem_no_import.py") is False

    def test_wrong_suffix(self):
        assert self.driver.detect(FIXTURES / "not_simulation.py") is False

    def test_missing(self):
        assert self.driver.detect(Path("/no/such.py")) is False


class TestLint:
    def setup_method(self):
        self.driver = PymfemDriver()

    def test_good(self):
        assert self.driver.lint(FIXTURES / "mfem_good.py").ok is True

    def test_no_import_error(self):
        assert self.driver.lint(FIXTURES / "mfem_no_import.py").ok is False

    def test_no_usage_warn(self):
        r = self.driver.lint(FIXTURES / "mfem_no_mesh.py")
        assert r.ok is True
        assert any(d.level == "warning" for d in r.diagnostics)

    def test_syntax_error(self):
        assert self.driver.lint(FIXTURES / "mfem_syntax_error.py").ok is False

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
        d = PymfemDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [])
        assert d.connect().status == "not_installed"

    def test_found(self, monkeypatch):
        from sim.driver import SolverInstall
        d = PymfemDriver()
        monkeypatch.setattr(
            d, "detect_installed",
            lambda: [SolverInstall(
                name="pymfem", version="4.8", path="/x", source="test",
                extra={"python": "/x/python", "raw_version": "4.8.0.1"},
            )],
        )
        assert d.connect().status == "ok"


class TestParseOutput:
    def setup_method(self):
        self.driver = PymfemDriver()

    def test_last_json(self):
        stdout = 'info\n{"dofs": 121, "u_max": 0.073}\n'
        assert self.driver.parse_output(stdout)["dofs"] == 121

    def test_no_json(self):
        assert self.driver.parse_output("nothing") == {}


class TestRunFile:
    def test_raises_when_not_installed(self, monkeypatch):
        d = PymfemDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [])
        with pytest.raises(RuntimeError, match="(?i)pymfem|mfem"):
            d.run_file(FIXTURES / "mfem_good.py")

    def test_wrong_suffix(self, monkeypatch):
        from sim.driver import SolverInstall
        d = PymfemDriver()
        monkeypatch.setattr(
            d, "detect_installed",
            lambda: [SolverInstall(
                name="pymfem", version="4.8", path="/x", source="test",
                extra={"python": "/x/python"},
            )],
        )
        import os, tempfile
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            p = Path(f.name)
        try:
            with pytest.raises(RuntimeError, match="(?i)pymfem|mfem"):
                d.run_file(p)
        finally:
            os.unlink(p)
