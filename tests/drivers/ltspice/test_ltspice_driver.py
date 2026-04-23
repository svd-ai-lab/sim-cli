"""Tier 1 protocol-compliance tests for the LTspice driver."""
from __future__ import annotations

from pathlib import Path

import pytest

from sim.driver import SolverInstall
from sim.drivers.ltspice import LTspiceDriver
from sim.drivers.ltspice.driver import _parse_log

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"


class TestDetect:
    def setup_method(self):
        self.driver = LTspiceDriver()

    def test_good_net(self):
        assert self.driver.detect(FIXTURES / "ltspice_good.net") is True

    def test_cir_suffix(self, tmp_path):
        p = tmp_path / "x.cir"
        p.write_text("* hi\nV1 1 0 1\n.end\n")
        assert self.driver.detect(p) is True

    def test_sp_suffix(self, tmp_path):
        p = tmp_path / "x.sp"
        p.write_text("* hi\nV1 1 0 1\n.end\n")
        assert self.driver.detect(p) is True

    def test_wrong_suffix(self, tmp_path):
        p = tmp_path / "x.py"
        p.write_text("print('hi')\n")
        assert self.driver.detect(p) is False

    def test_missing(self):
        assert self.driver.detect(Path("/no/such.net")) is False


class TestLint:
    def setup_method(self):
        self.driver = LTspiceDriver()

    def test_good(self):
        assert self.driver.lint(FIXTURES / "ltspice_good.net").ok is True

    def test_empty(self):
        r = self.driver.lint(FIXTURES / "ltspice_empty.net")
        assert r.ok is False
        assert any("empty" in d.message.lower() for d in r.diagnostics)

    def test_no_analysis(self):
        r = self.driver.lint(FIXTURES / "ltspice_no_analysis.net")
        assert r.ok is False
        assert any("analysis" in d.message.lower() for d in r.diagnostics)

    def test_schematic_mis_suffixed(self):
        r = self.driver.lint(FIXTURES / "ltspice_schematic.net")
        assert r.ok is False
        assert any("schematic" in d.message.lower() for d in r.diagnostics)

    def test_wrong_suffix(self, tmp_path):
        p = tmp_path / "x.txt"
        p.write_text("* V1 1 0 1\n.tran 1m\n.end\n")
        assert self.driver.lint(p).ok is False


class TestConnect:
    def test_not_installed(self, monkeypatch):
        d = LTspiceDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [])
        info = d.connect()
        assert info.status == "not_installed"
        assert "SIM_LTSPICE_EXE" in info.message

    def test_found(self, monkeypatch):
        d = LTspiceDriver()
        monkeypatch.setattr(
            d, "detect_installed",
            lambda: [SolverInstall(
                name="ltspice", version="17.2.4",
                path="/Applications/LTspice.app", source="default-path:/Applications",
                extra={"exe": "/Applications/LTspice.app/Contents/MacOS/LTspice"},
            )],
        )
        info = d.connect()
        assert info.status == "ok"
        assert info.version == "17.2.4"


class TestParseOutput:
    def setup_method(self):
        self.driver = LTspiceDriver()

    def test_last_json_wins(self):
        stdout = 'banner\n{"measures": {"vout_pk": {"value": 0.999}}}\n'
        out = self.driver.parse_output(stdout)
        assert out["measures"]["vout_pk"]["value"] == 0.999

    def test_no_json(self):
        assert self.driver.parse_output("nope") == {}


class TestLogParser:
    """_parse_log is the core of output extraction — cover it directly."""

    def test_measure_with_from_to(self):
        log = (
            "solver = Normal\n"
            "vout_pk: MAX(v(out))=0.999955 FROM 0 TO 0.005\n"
            "Total elapsed time: 0.003 seconds.\n"
        )
        out = _parse_log(log)
        assert out["measures"]["vout_pk"]["value"] == pytest.approx(0.999955)
        assert out["measures"]["vout_pk"]["from"] == 0.0
        assert out["measures"]["vout_pk"]["to"] == 0.005
        assert out["elapsed_s"] == pytest.approx(0.003)
        assert out["errors"] == []
        assert out["warnings"] == []

    def test_measure_with_suffix_unit(self):
        log = "gain: V(out)/V(in)=2.5V\n"
        out = _parse_log(log)
        # regex strips trailing letters before float conversion
        assert out["measures"]["gain"]["value"] == 2.5

    def test_errors_detected(self):
        log = (
            "Error: convergence failed at step 1\n"
            "Singular matrix\n"
            "Total elapsed time: 0.001 seconds.\n"
        )
        out = _parse_log(log)
        assert len(out["errors"]) >= 1
        assert any("conv" in e.lower() or "singular" in e.lower() for e in out["errors"])

    def test_warnings_detected(self):
        log = "WARNING: node N001 floating\nOK otherwise\n"
        out = _parse_log(log)
        assert len(out["warnings"]) == 1
        assert "floating" in out["warnings"][0]


class TestRunFile:
    def test_wrong_suffix_raises(self, monkeypatch, tmp_path):
        d = LTspiceDriver()
        monkeypatch.setattr(
            d, "detect_installed",
            lambda: [SolverInstall(
                name="ltspice", version="17.2.4",
                path="/x", source="test",
                extra={"exe": "/x/LTspice"},
            )],
        )
        p = tmp_path / "x.txt"
        p.write_text("not a netlist")
        with pytest.raises(RuntimeError, match="(?i)ltspice"):
            d.run_file(p)

    def test_raises_when_not_installed(self, monkeypatch):
        d = LTspiceDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [])
        with pytest.raises(RuntimeError, match="(?i)ltspice"):
            d.run_file(FIXTURES / "ltspice_good.net")
