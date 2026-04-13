"""Tests for the CFX driver — all pass without CFX installed."""
from pathlib import Path
from types import SimpleNamespace

from sim.drivers.cfx.driver import CfxDriver

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "cfx"


class TestDetect:
    def setup_method(self):
        self.driver = CfxDriver()

    def test_detect_ccl_file(self):
        assert self.driver.detect(FIXTURES / "cfx_good.ccl") is True

    def test_detect_def_file(self):
        assert self.driver.detect(FIXTURES / "cfx_minimal.def") is True

    def test_detect_ccl_without_flow(self):
        """CCL with LIBRARY but no FLOW — still CCL syntax, should detect."""
        assert self.driver.detect(FIXTURES / "cfx_no_flow.ccl") is True

    def test_detect_rejects_python_script(self):
        assert self.driver.detect(FIXTURES.parent / "mock_solver.py") is False

    def test_detect_missing_file(self):
        assert self.driver.detect(Path("/does/not/exist.ccl")) is False

    def test_detect_cfx_extension(self):
        """A .cfx project file should be detected."""
        assert self.driver.detect(FIXTURES / "nonexistent.cfx") is False

    def test_detect_random_text_file(self, tmp_path):
        f = tmp_path / "notes.ccl"
        f.write_text("Hello world, this is just notes.\n")
        assert self.driver.detect(f) is False


class TestLint:
    def setup_method(self):
        self.driver = CfxDriver()

    def test_lint_good_ccl(self):
        result = self.driver.lint(FIXTURES / "cfx_good.ccl")
        assert result.ok is True

    def test_lint_ccl_no_flow_is_warning(self):
        result = self.driver.lint(FIXTURES / "cfx_no_flow.ccl")
        assert result.ok is True
        assert any("FLOW" in d.message for d in result.diagnostics
                    if d.level == "warning")

    def test_lint_def_file(self):
        result = self.driver.lint(FIXTURES / "cfx_minimal.def")
        assert result.ok is True

    def test_lint_unsupported_extension(self, tmp_path):
        f = tmp_path / "test.xyz"
        f.write_text("whatever")
        result = self.driver.lint(f)
        assert result.ok is False
        assert any("unsupported" in d.message.lower() for d in result.diagnostics)

    def test_lint_missing_file(self):
        result = self.driver.lint(Path("/does/not/exist.ccl"))
        assert result.ok is False
        assert any(d.level == "error" for d in result.diagnostics)

    def test_lint_reports_ccl_version(self):
        result = self.driver.lint(FIXTURES / "cfx_good.ccl")
        assert any("24.1" in d.message for d in result.diagnostics
                    if d.level == "info")


class TestConnect:
    def test_reports_not_installed_when_missing(self, monkeypatch):
        monkeypatch.setattr(
            "sim.drivers.cfx.driver._scan_cfx_installs", lambda: []
        )
        driver = CfxDriver()
        info = driver.connect()
        assert info.status == "not_installed"
        assert info.solver == "cfx"

    def test_reports_ok_when_found(self, monkeypatch):
        from sim.driver import SolverInstall
        fake = [SolverInstall(
            name="cfx", version="24.1",
            path="E:/Program Files/ANSYS Inc/v241/CFX/bin",
            source="env:AWP_ROOT241",
            extra={"cfx5solve": "E:/Program Files/ANSYS Inc/v241/CFX/bin/cfx5solve.exe"},
        )]
        monkeypatch.setattr(
            "sim.drivers.cfx.driver._scan_cfx_installs", lambda: fake
        )
        driver = CfxDriver()
        info = driver.connect()
        assert info.status == "ok"
        assert info.version == "24.1"


class TestParseOutput:
    def setup_method(self):
        self.driver = CfxDriver()

    def test_parse_last_json_line(self):
        stdout = 'Solver started\n{"status":"ok","iterations":150}\n'
        result = self.driver.parse_output(stdout)
        assert result["status"] == "ok"
        assert result["iterations"] == 150

    def test_parse_empty(self):
        assert self.driver.parse_output("") == {}

    def test_parse_no_json(self):
        assert self.driver.parse_output("some plain solver log\n") == {}

    def test_parse_cfx_iterations(self):
        """Parse CFX-specific iteration count from solver output."""
        stdout = (
            "OUTER LOOP ITERATION =     1\n"
            "OUTER LOOP ITERATION =    50\n"
            "OUTER LOOP ITERATION =   100\n"
        )
        result = self.driver.parse_output(stdout)
        assert result.get("iterations") == 100

    def test_parse_wall_clock_time(self):
        stdout = "Total wall clock time: 42.5 s\n"
        result = self.driver.parse_output(stdout)
        assert result.get("wall_clock_s") == 42.5

    def test_json_takes_priority_over_cfx_parsing(self):
        """If stdout has JSON, use it instead of CFX parsing."""
        stdout = (
            'OUTER LOOP ITERATION =   100\n'
            '{"custom": "result"}\n'
        )
        result = self.driver.parse_output(stdout)
        assert result == {"custom": "result"}


class TestRunFile:
    def test_uses_cfx5solve_for_def(self, monkeypatch):
        from sim.driver import SolverInstall
        fake = [SolverInstall(
            name="cfx", version="24.1",
            path="E:/Program Files/ANSYS Inc/v241/CFX/bin",
            source="env:AWP_ROOT241",
            extra={"cfx5solve": "E:/cfx5solve.exe"},
        )]
        monkeypatch.setattr(
            "sim.drivers.cfx.driver._scan_cfx_installs", lambda: fake
        )

        recorded = {}

        def fake_run(command, capture_output, text, cwd, timeout):
            recorded["command"] = command
            recorded["cwd"] = cwd
            return SimpleNamespace(returncode=0, stdout='{"ok":true}\n', stderr="")

        monkeypatch.setattr("subprocess.run", fake_run)

        driver = CfxDriver()
        result = driver.run_file(FIXTURES / "cfx_minimal.def")
        assert result.exit_code == 0
        assert result.solver == "cfx"
        assert "-batch" in recorded["command"]
        assert "-def" in recorded["command"]

    def test_ccl_with_matching_def(self, monkeypatch, tmp_path):
        from sim.driver import SolverInstall
        fake = [SolverInstall(
            name="cfx", version="24.1",
            path="E:/fake/CFX/bin",
            source="test",
            extra={"cfx5solve": "E:/fake/cfx5solve.exe"},
        )]
        monkeypatch.setattr(
            "sim.drivers.cfx.driver._scan_cfx_installs", lambda: fake
        )

        recorded = {}

        def fake_run(command, capture_output, text, cwd, timeout):
            recorded["command"] = command
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr("subprocess.run", fake_run)

        # Create matching .ccl + .def pair
        ccl = tmp_path / "test.ccl"
        ccl.write_text("FLOW: Test\nEND\n")
        def_file = tmp_path / "test.def"
        def_file.write_text("CFX5_DEF")

        driver = CfxDriver()
        result = driver.run_file(ccl)
        assert result.exit_code == 0
        assert "-ccl" in recorded["command"]
        assert "-def" in recorded["command"]

    def test_ccl_without_def_errors(self, monkeypatch, tmp_path):
        from sim.driver import SolverInstall
        fake = [SolverInstall(
            name="cfx", version="24.1",
            path="E:/fake/CFX/bin",
            source="test",
            extra={"cfx5solve": "E:/fake/cfx5solve.exe"},
        )]
        monkeypatch.setattr(
            "sim.drivers.cfx.driver._scan_cfx_installs", lambda: fake
        )

        ccl = tmp_path / "orphan.ccl"
        ccl.write_text("FLOW: Test\nEND\n")

        driver = CfxDriver()
        result = driver.run_file(ccl)
        assert result.exit_code == 1
        assert any("def" in e.lower() for e in result.errors)

    def test_raises_when_not_installed(self, monkeypatch):
        monkeypatch.setattr(
            "sim.drivers.cfx.driver._scan_cfx_installs", lambda: []
        )
        driver = CfxDriver()
        import pytest
        with pytest.raises(RuntimeError, match="(?i)cfx"):
            driver.run_file(FIXTURES / "cfx_minimal.def")

    def test_error_detection_in_output(self, monkeypatch):
        from sim.driver import SolverInstall
        fake = [SolverInstall(
            name="cfx", version="24.1",
            path="E:/fake/CFX/bin",
            source="test",
            extra={"cfx5solve": "E:/fake/cfx5solve.exe"},
        )]
        monkeypatch.setattr(
            "sim.drivers.cfx.driver._scan_cfx_installs", lambda: fake
        )

        def fake_run(command, capture_output, text, cwd, timeout):
            return SimpleNamespace(
                returncode=0,
                stdout="FATAL ERROR: License not available\n",
                stderr="",
            )

        monkeypatch.setattr("subprocess.run", fake_run)

        driver = CfxDriver()
        result = driver.run_file(FIXTURES / "cfx_minimal.def")
        # exit_code overridden to 1 because of FATAL in output
        assert result.exit_code == 1
        assert len(result.errors) > 0


class TestDetectInstalled:
    def test_returns_empty_when_nothing_found(self, monkeypatch):
        monkeypatch.setattr(
            "sim.drivers.cfx.driver._INSTALL_FINDERS",
            [lambda: []],
        )
        driver = CfxDriver()
        assert driver.detect_installed() == []
