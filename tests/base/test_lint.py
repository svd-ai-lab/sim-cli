"""Tests for `sim lint` — driver-agnostic CLI behavior.

Driver-specific lint tests live in each plugin's own test suite (e.g.
`sim-plugin-coolprop/tests/test_coolprop_driver.py`) since the lint
logic moved out of sim-cli's tree alongside its driver in the Phase 2
extractions.

This file covers the parts that are still sim-cli's responsibility:

  - lint exits non-zero when no registered driver matches the script.
  - JSON output mode emits a structured LintResult.
"""
from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from sim.cli import main


FIXTURES = Path(__file__).parent.parent / "fixtures"


class TestLintCLI:
    def test_no_driver_matched_exits_nonzero(self, tmp_path: Path):
        """A plain Python script that no driver claims should fail lint."""
        plain = tmp_path / "plain.py"
        plain.write_text("print('hello')\n")

        runner = CliRunner()
        result = runner.invoke(main, ["lint", str(plain)])
        # Lint exits 1 on failure (sim.cli.lint sys.exit at end).
        assert result.exit_code == 1
        assert "no registered driver" in result.output.lower()

    def test_json_output_emits_lint_result(self, tmp_path: Path):
        plain = tmp_path / "plain.py"
        plain.write_text("print('hello')\n")

        runner = CliRunner()
        result = runner.invoke(main, ["--json", "lint", str(plain)])
        # Parse the JSON; ok must be False, diagnostics must be present.
        data = json.loads(result.output)
        assert data["ok"] is False
        assert "diagnostics" in data
        assert any("driver" in d.get("message", "").lower()
                   for d in data["diagnostics"])
