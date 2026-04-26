"""Protocol-compliance tests for the LTspice driver.

The driver itself is now a thin adapter over ``sim_ltspice``; heavy
file-format testing (log parsing, raw header parsing, install discovery)
lives in the sim-ltspice repo. These tests exercise only the adapter
surface that sim-cli is responsible for: `detect`, `lint`, `connect`,
`parse_output`, and the glue in `run_file`.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from sim.driver import SolverInstall
from sim.drivers.ltspice import LTspiceDriver

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

    def test_asc_suffix(self, tmp_path):
        p = tmp_path / "x.asc"
        p.write_text("Version 4\nSHEET 1 880 680\n")
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


class TestLintAsc:
    def setup_method(self):
        self.driver = LTspiceDriver()

    def test_good_asc(self, tmp_path):
        p = tmp_path / "rc.asc"
        p.write_text(
            "Version 4\nSHEET 1 880 680\n"
            "SYMBOL res 0 0 R0\nSYMATTR InstName R1\n"
            "TEXT 0 200 Left 2 !.tran 0 5m\n"
        )
        assert self.driver.lint(p).ok is True

    def test_empty_asc(self, tmp_path):
        p = tmp_path / "x.asc"
        p.write_text("")
        r = self.driver.lint(p)
        assert r.ok is False
        assert any("empty" in d.message.lower() for d in r.diagnostics)

    def test_missing_version_header(self, tmp_path):
        p = tmp_path / "x.asc"
        p.write_text("not a real schematic\nTEXT 0 0 Left 2 !.tran 1m\n")
        r = self.driver.lint(p)
        assert r.ok is False
        assert any("version" in d.message.lower() for d in r.diagnostics)

    def test_no_analysis_directive(self, tmp_path):
        p = tmp_path / "x.asc"
        p.write_text("Version 4\nSHEET 1 880 680\nSYMBOL res 0 0 R0\n")
        r = self.driver.lint(p)
        assert r.ok is False
        assert any("analysis" in d.message.lower() for d in r.diagnostics)


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


class TestDetectInstalled:
    def test_maps_sim_ltspice_install_to_solver(self, monkeypatch):
        """detect_installed delegates to sim_ltspice.find_ltspice and maps the
        Install dataclass to sim-cli's SolverInstall shape."""
        from sim_ltspice.install import Install

        fake_exe = Path("/fake/LTspice")
        fake = Install(
            exe=fake_exe,
            version="26.0.1",
            path="/fake",
            source="env:SIM_LTSPICE_EXE",
        )
        monkeypatch.setattr(
            "sim.drivers.ltspice.driver.find_ltspice", lambda: [fake]
        )
        [inst] = LTspiceDriver().detect_installed()
        assert isinstance(inst, SolverInstall)
        assert inst.name == "ltspice"
        assert inst.version == "26.0.1"
        assert inst.source == "env:SIM_LTSPICE_EXE"
        # str(Path(...)) emits OS-native separators — compare portably
        assert inst.extra["exe"] == str(fake_exe)


class TestParseOutput:
    def setup_method(self):
        self.driver = LTspiceDriver()

    def test_last_json_wins(self):
        stdout = 'banner\n{"measures": {"vout_pk": {"value": 0.999}}}\n'
        out = self.driver.parse_output(stdout)
        assert out["measures"]["vout_pk"]["value"] == 0.999

    def test_no_json(self):
        assert self.driver.parse_output("nope") == {}


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

    def test_folds_sim_ltspice_result_into_json_summary(self, monkeypatch):
        """run_file translates sim_ltspice.RunResult into a sim-cli RunResult
        with the JSON summary appended to stdout."""
        from sim_ltspice import RunResult as LtRunResult
        from sim_ltspice.log import LogResult, Measure

        d = LTspiceDriver()
        monkeypatch.setattr(
            d, "detect_installed",
            lambda: [SolverInstall(
                name="ltspice", version="17.2.4", path="/x", source="test",
                extra={"exe": "/x/LTspice"},
            )],
        )

        script = FIXTURES / "ltspice_good.net"
        log_path = script.with_suffix(".log")
        raw_path = script.with_suffix(".raw")

        fake_log = LogResult(
            measures={
                "vout_pk": Measure(expr="MAX(V(out))", value=0.999955,
                                   window_from=0.0, window_to=0.005)
            },
            errors=[],
            warnings=["WARNING: node N001 floating"],
            elapsed_s=0.003,
        )
        fake_lt = LtRunResult(
            exit_code=0, stdout="", stderr="",
            duration_s=0.12, script=script, started_at="",
            log=fake_log,
            log_path=log_path, raw_path=raw_path,
            raw_traces=["time", "V(out)", "V(in)"],
        )
        monkeypatch.setattr(
            "sim.drivers.ltspice.driver.run_net", lambda _s: fake_lt
        )

        result = d.run_file(script)
        assert result.exit_code == 0
        parsed = d.parse_output(result.stdout)
        assert parsed["measures"]["vout_pk"]["value"] == pytest.approx(0.999955)
        assert parsed["measures"]["vout_pk"]["from"] == 0.0
        assert parsed["measures"]["vout_pk"]["to"] == 0.005
        assert parsed["traces"] == ["time", "V(out)", "V(in)"]
        assert parsed["warnings"] == ["WARNING: node N001 floating"]
        assert parsed["log"] == str(log_path)
        assert parsed["raw"] == str(raw_path)

    def test_log_errors_promote_exit_code(self, monkeypatch):
        """Errors found in the .log file force exit_code != 0 even when
        LTspice itself exited cleanly."""
        from sim_ltspice import RunResult as LtRunResult
        from sim_ltspice.log import LogResult

        d = LTspiceDriver()
        monkeypatch.setattr(
            d, "detect_installed",
            lambda: [SolverInstall(
                name="ltspice", version="17.2.4", path="/x", source="test",
                extra={"exe": "/x/LTspice"},
            )],
        )
        fake_log = LogResult(
            errors=["Error: convergence failed"],
        )
        script = FIXTURES / "ltspice_good.net"
        fake_lt = LtRunResult(
            exit_code=0, stdout="", stderr="",
            duration_s=0.01, script=script, started_at="",
            log=fake_log, log_path=None, raw_path=None, raw_traces=[],
        )
        monkeypatch.setattr(
            "sim.drivers.ltspice.driver.run_net", lambda _s: fake_lt
        )
        result = d.run_file(script)
        assert result.exit_code == 1
        assert any("convergence" in e.lower() for e in result.errors)

    def test_asc_dispatches_to_run_asc(self, monkeypatch, tmp_path):
        """A `.asc` input must reach run_asc, not run_net."""
        from sim_ltspice import RunResult as LtRunResult
        from sim_ltspice.log import LogResult

        d = LTspiceDriver()
        monkeypatch.setattr(
            d, "detect_installed",
            lambda: [SolverInstall(
                name="ltspice", version="17.2.4", path="/x", source="test",
                extra={"exe": "/x/LTspice"},
            )],
        )

        asc = tmp_path / "rc.asc"
        asc.write_text("Version 4\nSHEET 1 880 680\n")

        called: dict[str, object] = {}

        def fake_asc(script):
            called["asc"] = Path(script)
            return LtRunResult(
                exit_code=0, stdout="", stderr="",
                duration_s=0.01, script=Path(script), started_at="",
                log=LogResult(), log_path=None, raw_path=None, raw_traces=[],
            )

        def fake_net(_script):
            called["net"] = True
            raise AssertionError("run_net must not be called for .asc")

        monkeypatch.setattr("sim.drivers.ltspice.driver.run_asc", fake_asc)
        monkeypatch.setattr("sim.drivers.ltspice.driver.run_net", fake_net)

        result = d.run_file(asc)
        assert called["asc"] == asc
        assert "net" not in called
        assert result.exit_code == 0
        assert result.solver == "ltspice"

    def test_flatten_error_maps_to_runtime_error(self, monkeypatch, tmp_path):
        """A FlattenError from sim_ltspice must surface as RuntimeError."""
        from sim_ltspice.netlist import FlattenError as LtFlattenError

        d = LTspiceDriver()
        monkeypatch.setattr(
            d, "detect_installed",
            lambda: [SolverInstall(
                name="ltspice", version="17.2.4", path="/x", source="test",
                extra={"exe": "/x/LTspice"},
            )],
        )

        asc = tmp_path / "x.asc"
        asc.write_text("Version 4\nSHEET 1 880 680\n")

        def boom(_script):
            raise LtFlattenError("symbol 'no_such' not found in catalog")

        monkeypatch.setattr("sim.drivers.ltspice.driver.run_asc", boom)
        with pytest.raises(RuntimeError, match="(?i)flatten"):
            d.run_file(asc)
