"""Tier 1 tests for CoolProp driver."""
from __future__ import annotations
from pathlib import Path
import pytest
from sim.drivers.coolprop import CoolPropDriver

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"


class TestDetect:
    def setup_method(self): self.d = CoolPropDriver()
    def test_good(self): assert self.d.detect(FIXTURES / "coolprop_good.py")
    def test_no_import(self): assert not self.d.detect(FIXTURES / "coolprop_no_import.py")
    def test_wrong_suffix(self): assert not self.d.detect(FIXTURES / "not_simulation.py")
    def test_missing(self): assert not self.d.detect(Path("/no/such.py"))


class TestLint:
    def setup_method(self): self.d = CoolPropDriver()
    def test_good(self): assert self.d.lint(FIXTURES / "coolprop_good.py").ok
    def test_no_import(self): assert not self.d.lint(FIXTURES / "coolprop_no_import.py").ok
    def test_no_usage(self):
        r = self.d.lint(FIXTURES / "coolprop_no_usage.py")
        assert r.ok and any(x.level == "warning" for x in r.diagnostics)
    def test_syntax(self): assert not self.d.lint(FIXTURES / "coolprop_syntax_error.py").ok
    def test_wrong_suffix(self):
        import os, tempfile
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f: p = Path(f.name)
        try: assert not self.d.lint(p).ok
        finally: os.unlink(p)


class TestConnect:
    def test_not_installed(self, monkeypatch):
        d = CoolPropDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [])
        assert d.connect().status == "not_installed"
    def test_found(self, monkeypatch):
        from sim.driver import SolverInstall
        d = CoolPropDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [SolverInstall(
            name="coolprop", version="6.4", path="/x", source="t",
            extra={"python": "/x/python", "raw_version": "6.4.1"})])
        assert d.connect().status == "ok"


class TestParseOutput:
    def setup_method(self): self.d = CoolPropDriver()
    def test_last_json(self):
        assert self.d.parse_output('foo\n{"T_sat_K": 373.12}\n')["T_sat_K"] == 373.12


class TestRunFile:
    def test_raises_when_not_installed(self, monkeypatch):
        d = CoolPropDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [])
        with pytest.raises(RuntimeError, match="(?i)coolprop"):
            d.run_file(FIXTURES / "coolprop_good.py")
    def test_wrong_suffix(self, monkeypatch):
        from sim.driver import SolverInstall
        d = CoolPropDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [SolverInstall(
            name="coolprop", version="6.4", path="/x", source="t",
            extra={"python": "/x/python"})])
        import os, tempfile
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f: p = Path(f.name)
        try:
            with pytest.raises(RuntimeError, match="(?i)coolprop"):
                d.run_file(p)
        finally: os.unlink(p)


class TestSessionStubs:
    """CoolProp is one-shot; DriverProtocol still requires the methods exist."""

    def setup_method(self): self.d = CoolPropDriver()

    def test_supports_session_false(self): assert self.d.supports_session is False

    def test_launch_raises(self):
        with pytest.raises(NotImplementedError, match="(?i)session"):
            self.d.launch()

    def test_run_raises(self):
        with pytest.raises(NotImplementedError, match="(?i)session"):
            self.d.run("PropsSI('T', 'P', 1e5, 'Q', 0, 'Water')")

    def test_disconnect_idempotent(self):
        r = self.d.disconnect()
        assert r == {"ok": True, "disconnected": True}
