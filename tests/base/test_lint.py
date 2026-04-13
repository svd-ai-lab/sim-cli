"""Tests for sim lint — Phase 1."""
from pathlib import Path

from click.testing import CliRunner

from sim.cli import main
from sim.drivers.pybamm import PyBaMMLDriver

FIXTURES = Path(__file__).parent.parent / "fixtures"


class TestPyBaMMDetect:
    def test_detects_pybamm_script(self):
        driver = PyBaMMLDriver()
        assert driver.detect(FIXTURES / "pybamm" / "pybamm_spm_good.py") is True

    def test_rejects_non_pybamm_script(self):
        driver = PyBaMMLDriver()
        assert driver.detect(FIXTURES / "not_simulation.py") is False

    def test_detects_bad_import_script(self):
        """Script uses pybamm without importing — detect should return False."""
        driver = PyBaMMLDriver()
        assert driver.detect(FIXTURES / "pybamm" / "pybamm_bad_import.py") is False


class TestPyBaMMLint:
    def test_good_script_passes(self):
        driver = PyBaMMLDriver()
        result = driver.lint(FIXTURES / "pybamm" / "pybamm_spm_good.py")
        assert result.ok is True
        assert not any(d.level == "error" for d in result.diagnostics)

    def test_missing_import_fails(self):
        driver = PyBaMMLDriver()
        result = driver.lint(FIXTURES / "pybamm" / "pybamm_bad_import.py")
        assert result.ok is False
        errors = [d for d in result.diagnostics if d.level == "error"]
        assert len(errors) >= 1
        assert "import" in errors[0].message.lower()

    def test_no_solve_warns(self):
        driver = PyBaMMLDriver()
        result = driver.lint(FIXTURES / "pybamm" / "pybamm_no_solve.py")
        warnings = [d for d in result.diagnostics if d.level == "warning"]
        assert len(warnings) >= 1
        assert "solve" in warnings[0].message.lower()


class TestLintCLI:
    def test_exit_code_zero_good(self):
        runner = CliRunner()
        result = runner.invoke(main, ["lint", str(FIXTURES / "pybamm" / "pybamm_spm_good.py")])
        assert result.exit_code == 0

    def test_exit_code_one_bad(self):
        runner = CliRunner()
        result = runner.invoke(main, ["lint", str(FIXTURES / "pybamm" / "pybamm_bad_import.py")])
        assert result.exit_code == 1

    def test_json_output(self):
        import json

        runner = CliRunner()
        result = runner.invoke(
            main, ["--json", "lint", str(FIXTURES / "pybamm" / "pybamm_spm_good.py")]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "ok" in data
        assert "diagnostics" in data
