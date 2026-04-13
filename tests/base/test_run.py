"""Tests for sim run — Phase 2."""
import json
from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner

from sim.cli import main
from sim.runner import execute_script

FIXTURES = Path(__file__).parent.parent / "fixtures"


class TestRunner:
    def test_captures_stdout(self):
        result = execute_script(FIXTURES / "mock_solver.py")
        assert "3.72" in result.stdout

    def test_exit_code_zero(self):
        result = execute_script(FIXTURES / "mock_solver.py")
        assert result.exit_code == 0

    def test_exit_code_nonzero(self):
        result = execute_script(FIXTURES / "mock_fail.py")
        assert result.exit_code == 1

    def test_captures_stderr(self):
        result = execute_script(FIXTURES / "mock_fail.py")
        assert "something went wrong" in result.stderr

    def test_measures_duration(self):
        result = execute_script(FIXTURES / "mock_solver.py")
        assert result.duration_s > 0

    def test_records_timestamp(self):
        from datetime import datetime

        result = execute_script(FIXTURES / "mock_solver.py")
        # Should be valid ISO format
        datetime.fromisoformat(result.timestamp)

    def test_delegates_to_driver_run_file(self):
        fake = SimpleNamespace(
            run_file=lambda script: SimpleNamespace(
                exit_code=0,
                stdout="delegated",
                stderr="",
                duration_s=0.1,
                script=str(script),
                solver="matlab",
                timestamp="2026-01-01T00:00:00+00:00",
            )
        )
        result = execute_script(FIXTURES / "matlab" / "matlab_ok.m", solver="matlab", driver=fake)
        assert result.stdout == "delegated"


class TestRunCLI:
    def test_run_success(self):
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["run", "--solver=pybamm", str(FIXTURES / "mock_solver.py")],
        )
        assert result.exit_code == 0
        assert "3.72" in result.output or "converged" in result.output.lower() or "exit_code" in result.output.lower()

    def test_run_json_output(self):
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--json", "run", "--solver=pybamm", str(FIXTURES / "mock_solver.py")],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "exit_code" in data
        assert "duration_s" in data
