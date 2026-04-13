"""Tests for sim check (solver availability)."""
import json

from click.testing import CliRunner

from sim.cli import main


class TestCheckCLI:
    def test_unknown_solver(self):
        runner = CliRunner()
        result = runner.invoke(main, ["check", "unknown"])
        assert result.exit_code == 1
        assert "unknown solver" in result.output.lower()

    def test_check_json(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--json", "check", "pybamm"])
        # May fail if pybamm not installed, but should still be valid JSON
        if result.exit_code == 0:
            data = json.loads(result.output)
            # New layered response shape: {"ok": bool, "data": {...}}
            assert "ok" in data
            assert "data" in data
            assert data["data"]["solver"] == "pybamm"
            assert "compatibility" in data["data"]
