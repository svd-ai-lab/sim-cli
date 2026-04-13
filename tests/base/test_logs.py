"""Tests for sim logs command."""
import json
from pathlib import Path

from click.testing import CliRunner

from sim.cli import main

FIXTURES = Path(__file__).parent.parent / "fixtures"


class TestLogsCLI:
    def _run_mock(self, runner, env):
        runner.invoke(
            main,
            ["run", "--solver=pybamm", str(FIXTURES / "mock_solver.py")],
            env=env,
        )

    def test_empty(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(main, ["logs"], env={"SIM_DIR": str(tmp_path / ".sim")})
        assert result.exit_code == 0
        assert "no runs" in result.output.lower()

    def test_list_runs(self, tmp_path):
        runner = CliRunner()
        env = {"SIM_DIR": str(tmp_path / ".sim")}
        self._run_mock(runner, env)
        result = runner.invoke(main, ["logs"], env=env)
        assert result.exit_code == 0
        assert "001" in result.output
        assert "pybamm" in result.output

    def test_list_json(self, tmp_path):
        runner = CliRunner()
        env = {"SIM_DIR": str(tmp_path / ".sim")}
        self._run_mock(runner, env)
        result = runner.invoke(main, ["--json", "logs"], env=env)
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 1

    def test_show_last(self, tmp_path):
        runner = CliRunner()
        env = {"SIM_DIR": str(tmp_path / ".sim")}
        self._run_mock(runner, env)
        result = runner.invoke(main, ["logs", "last"], env=env)
        assert result.exit_code == 0
        assert "3.72" in result.output

    def test_show_by_id(self, tmp_path):
        runner = CliRunner()
        env = {"SIM_DIR": str(tmp_path / ".sim")}
        self._run_mock(runner, env)
        result = runner.invoke(main, ["logs", "001", "--field=voltage_V"], env=env)
        assert result.exit_code == 0
        assert "3.72" in result.output

    def test_field_extraction(self, tmp_path):
        runner = CliRunner()
        env = {"SIM_DIR": str(tmp_path / ".sim")}
        self._run_mock(runner, env)
        result = runner.invoke(main, ["logs", "last", "--field=voltage_V"], env=env)
        assert result.exit_code == 0
        assert "3.72" in result.output

    def test_field_missing(self, tmp_path):
        runner = CliRunner()
        env = {"SIM_DIR": str(tmp_path / ".sim")}
        self._run_mock(runner, env)
        result = runner.invoke(main, ["logs", "last", "--field=nonexistent"], env=env)
        assert result.exit_code == 1

    def test_show_json(self, tmp_path):
        runner = CliRunner()
        env = {"SIM_DIR": str(tmp_path / ".sim")}
        self._run_mock(runner, env)
        result = runner.invoke(main, ["--json", "logs", "last"], env=env)
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "voltage_V" in data
