"""Tier 1 tests for Pyomo driver."""
from __future__ import annotations
from pathlib import Path
import pytest
from sim.drivers.pyomo import PyomoDriver

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"


class TestDetect:
    def setup_method(self): self.d = PyomoDriver()
    def test_good(self): assert self.d.detect(FIXTURES / "pyomo_good.py")
    def test_no_import(self): assert not self.d.detect(FIXTURES / "pyomo_no_import.py")
    def test_wrong_suffix(self): assert not self.d.detect(FIXTURES / "not_simulation.py")
    def test_missing(self): assert not self.d.detect(Path("/no/such.py"))


class TestLint:
    def setup_method(self): self.d = PyomoDriver()
    def test_good(self): assert self.d.lint(FIXTURES / "pyomo_good.py").ok
    def test_no_import(self): assert not self.d.lint(FIXTURES / "pyomo_no_import.py").ok
    def test_no_usage(self):
        r = self.d.lint(FIXTURES / "pyomo_no_usage.py")
        assert r.ok and any(x.level == "warning" for x in r.diagnostics)
    def test_syntax(self): assert not self.d.lint(FIXTURES / "pyomo_syntax_error.py").ok
    def test_wrong_suffix(self):
        import os, tempfile
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f: p = Path(f.name)
        try: assert not self.d.lint(p).ok
        finally: os.unlink(p)


class TestConnect:
    def test_not_installed(self, monkeypatch):
        d = PyomoDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [])
        assert d.connect().status == "not_installed"
    def test_found(self, monkeypatch):
        from sim.driver import SolverInstall
        d = PyomoDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [SolverInstall(
            name="pyomo", version="6.6", path="/x", source="t",
            extra={"python": "/x/python", "raw_version": "6.6.2"})])
        assert d.connect().status == "ok"


class TestParseOutput:
    def setup_method(self): self.d = PyomoDriver()
    def test_last_json(self):
        assert self.d.parse_output('HiGHS log\n{"obj": 36.0}\n')["obj"] == 36.0


class TestRunFile:
    def test_raises_when_not_installed(self, monkeypatch):
        d = PyomoDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [])
        with pytest.raises(RuntimeError, match="(?i)pyomo"):
            d.run_file(FIXTURES / "pyomo_good.py")
    def test_wrong_suffix(self, monkeypatch):
        from sim.driver import SolverInstall
        d = PyomoDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [SolverInstall(
            name="pyomo", version="6.6", path="/x", source="t",
            extra={"python": "/x/python"})])
        import os, tempfile
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f: p = Path(f.name)
        try:
            with pytest.raises(RuntimeError, match="(?i)pyomo"):
                d.run_file(p)
        finally: os.unlink(p)
