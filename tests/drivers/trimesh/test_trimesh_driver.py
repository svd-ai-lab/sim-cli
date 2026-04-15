"""Tier 1 tests for Trimesh driver."""
from __future__ import annotations
from pathlib import Path
import pytest
from sim.drivers.trimesh import TrimeshDriver

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"


class TestDetect:
    def setup_method(self): self.d = TrimeshDriver()
    def test_good(self): assert self.d.detect(FIXTURES / "trimesh_good.py")
    def test_no_import(self): assert not self.d.detect(FIXTURES / "trimesh_no_import.py")
    def test_wrong_suffix(self): assert not self.d.detect(FIXTURES / "not_simulation.py")
    def test_missing(self): assert not self.d.detect(Path("/no/such.py"))


class TestLint:
    def setup_method(self): self.d = TrimeshDriver()
    def test_good(self): assert self.d.lint(FIXTURES / "trimesh_good.py").ok
    def test_no_import(self): assert not self.d.lint(FIXTURES / "trimesh_no_import.py").ok
    def test_no_usage(self):
        r = self.d.lint(FIXTURES / "trimesh_no_usage.py")
        assert r.ok and any(x.level == "warning" for x in r.diagnostics)
    def test_syntax(self): assert not self.d.lint(FIXTURES / "trimesh_syntax_error.py").ok
    def test_wrong_suffix(self):
        import os, tempfile
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f: p = Path(f.name)
        try: assert not self.d.lint(p).ok
        finally: os.unlink(p)


class TestConnect:
    def test_not_installed(self, monkeypatch):
        d = TrimeshDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [])
        assert d.connect().status == "not_installed"
    def test_found(self, monkeypatch):
        from sim.driver import SolverInstall
        d = TrimeshDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [SolverInstall(
            name="trimesh", version="4.4", path="/x", source="t",
            extra={"python": "/x/python", "raw_version": "4.4.1"})])
        assert d.connect().status == "ok"


class TestParseOutput:
    def setup_method(self): self.d = TrimeshDriver()
    def test_last_json(self):
        assert self.d.parse_output('foo\n{"volume": 24.0}\n')["volume"] == 24.0


class TestRunFile:
    def test_raises_when_not_installed(self, monkeypatch):
        d = TrimeshDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [])
        with pytest.raises(RuntimeError, match="(?i)trimesh"):
            d.run_file(FIXTURES / "trimesh_good.py")
    def test_wrong_suffix(self, monkeypatch):
        from sim.driver import SolverInstall
        d = TrimeshDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [SolverInstall(
            name="trimesh", version="4.4", path="/x", source="t",
            extra={"python": "/x/python"})])
        import os, tempfile
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f: p = Path(f.name)
        try:
            with pytest.raises(RuntimeError, match="(?i)trimesh"):
                d.run_file(p)
        finally: os.unlink(p)
