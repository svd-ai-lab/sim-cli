"""Tests for sim logs command.

Backed by the global history store at $SIM_HOME/history.jsonl (issue #5).
Tests isolate with monkeypatch on SIM_HOME.
"""
import json
from pathlib import Path

from click.testing import CliRunner

from sim.cli import main

FIXTURES = Path(__file__).parent.parent / "fixtures"


class TestLogsCLI:
    def _run_mock(self, runner, env):
        return runner.invoke(
            main,
            ["run", "--solver=coolprop", str(FIXTURES / "mock_solver.py")],
            env=env,
        )

    def test_empty(self, tmp_path):
        runner = CliRunner()
        env = {"SIM_HOME": str(tmp_path / ".sim")}
        result = runner.invoke(main, ["logs", "--all"], env=env)
        assert result.exit_code == 0
        assert "no runs" in result.output.lower()

    def test_list_runs(self, tmp_path):
        runner = CliRunner()
        env = {"SIM_HOME": str(tmp_path / ".sim")}
        self._run_mock(runner, env)
        result = runner.invoke(main, ["logs", "--all"], env=env)
        assert result.exit_code == 0
        assert "001" in result.output
        assert "coolprop" in result.output

    def test_list_json(self, tmp_path):
        runner = CliRunner()
        env = {"SIM_HOME": str(tmp_path / ".sim")}
        self._run_mock(runner, env)
        result = runner.invoke(main, ["--json", "logs", "--all"], env=env)
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["solver"] == "coolprop"

    def test_show_last(self, tmp_path):
        runner = CliRunner()
        env = {"SIM_HOME": str(tmp_path / ".sim")}
        self._run_mock(runner, env)
        result = runner.invoke(main, ["logs", "last", "--all"], env=env)
        assert result.exit_code == 0
        assert "3.72" in result.output

    def test_show_by_id(self, tmp_path):
        runner = CliRunner()
        env = {"SIM_HOME": str(tmp_path / ".sim")}
        self._run_mock(runner, env)
        result = runner.invoke(main, ["logs", "001", "--field=voltage_V", "--all"], env=env)
        assert result.exit_code == 0
        assert "3.72" in result.output

    def test_field_extraction(self, tmp_path):
        runner = CliRunner()
        env = {"SIM_HOME": str(tmp_path / ".sim")}
        self._run_mock(runner, env)
        result = runner.invoke(main, ["logs", "last", "--field=voltage_V", "--all"], env=env)
        assert result.exit_code == 0
        assert "3.72" in result.output

    def test_field_missing(self, tmp_path):
        runner = CliRunner()
        env = {"SIM_HOME": str(tmp_path / ".sim")}
        self._run_mock(runner, env)
        result = runner.invoke(main, ["logs", "last", "--field=nonexistent", "--all"], env=env)
        assert result.exit_code == 1

    def test_show_json(self, tmp_path):
        runner = CliRunner()
        env = {"SIM_HOME": str(tmp_path / ".sim")}
        self._run_mock(runner, env)
        result = runner.invoke(main, ["--json", "logs", "last", "--all"], env=env)
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "voltage_V" in data

    def test_filter_by_solver(self, tmp_path):
        runner = CliRunner()
        env = {"SIM_HOME": str(tmp_path / ".sim")}
        self._run_mock(runner, env)
        result = runner.invoke(main, ["logs", "--solver=coolprop", "--all"], env=env)
        assert result.exit_code == 0
        assert "001" in result.output
        result2 = runner.invoke(main, ["logs", "--solver=fluent", "--all"], env=env)
        assert result2.exit_code == 0
        assert "no runs" in result2.output.lower()
