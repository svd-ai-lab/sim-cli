"""Tier 1 tests for pymoo driver."""
from __future__ import annotations
from pathlib import Path
import pytest
from sim.drivers.pymoo import PymooDriver

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"


class TestDetect:
    def setup_method(self): self.d = PymooDriver()
    def test_good(self): assert self.d.detect(FIXTURES / "pymoo_good.py")
    def test_no_import(self): assert not self.d.detect(FIXTURES / "pymoo_no_import.py")
    def test_wrong_suffix(self): assert not self.d.detect(FIXTURES / "not_simulation.py")
    def test_missing(self): assert not self.d.detect(Path("/no/such.py"))


class TestLint:
    def setup_method(self): self.d = PymooDriver()
    def test_good(self): assert self.d.lint(FIXTURES / "pymoo_good.py").ok
    def test_no_import(self): assert not self.d.lint(FIXTURES / "pymoo_no_import.py").ok
    def test_no_usage(self):
        r = self.d.lint(FIXTURES / "pymoo_no_usage.py")
        assert r.ok and any(x.level == "warning" for x in r.diagnostics)
    def test_syntax(self): assert not self.d.lint(FIXTURES / "pymoo_syntax_error.py").ok
    def test_wrong_suffix(self):
        import os, tempfile
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f: p = Path(f.name)
        try: assert not self.d.lint(p).ok
        finally: os.unlink(p)


class TestConnect:
    def test_not_installed(self, monkeypatch):
        d = PymooDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [])
        assert d.connect().status == "not_installed"

    def test_found(self, monkeypatch):
        from sim.driver import SolverInstall
        d = PymooDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [SolverInstall(
            name="pymoo", version="0.6", path="/x", source="t",
            extra={"python": "/x/python", "raw_version": "0.6.0"})])
        assert d.connect().status == "ok"


class TestParseOutput:
    def setup_method(self): self.d = PymooDriver()
    def test_last_json(self):
        assert self.d.parse_output('foo\n{"n_pareto": 36}\n')["n_pareto"] == 36


class TestRunFile:
    def test_raises_when_not_installed(self, monkeypatch):
        d = PymooDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [])
        with pytest.raises(RuntimeError, match="(?i)pymoo"):
            d.run_file(FIXTURES / "pymoo_good.py")

    def test_wrong_suffix(self, monkeypatch):
        from sim.driver import SolverInstall
        d = PymooDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [SolverInstall(
            name="pymoo", version="0.6", path="/x", source="t",
            extra={"python": "/x/python"})])
        import os, tempfile
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f: p = Path(f.name)
        try:
            with pytest.raises(RuntimeError, match="(?i)pymoo"):
                d.run_file(p)
        finally: os.unlink(p)
