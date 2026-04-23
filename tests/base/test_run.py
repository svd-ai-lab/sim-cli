"""Tests for sim run — Phase 2."""
import json
import textwrap
import tempfile
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

    # ── probe output tests ──────────────────────────────────────────────────

    def test_run_produces_diagnostics(self):
        """execute_script returns diagnostics list (may be empty, never None)."""
        result = execute_script(FIXTURES / "mock_solver.py")
        assert isinstance(result.diagnostics, list)

    def test_run_process_meta_probe(self):
        """ProcessMetaProbe fires on success: code sim.process.exit_zero."""
        result = execute_script(FIXTURES / "mock_solver.py")
        codes = [d["code"] for d in result.diagnostics]
        assert "sim.process.exit_zero" in codes

    def test_run_process_meta_failure(self):
        """ProcessMetaProbe fires on failure: code sim.process.exit_nonzero."""
        result = execute_script(FIXTURES / "mock_fail.py")
        codes = [d["code"] for d in result.diagnostics]
        assert "sim.process.exit_nonzero" in codes

    def test_run_stdout_json_tail_probe(self):
        """StdoutJsonTailProbe detects last JSON line on stdout."""
        result = execute_script(FIXTURES / "mock_solver.py")
        codes = [d["code"] for d in result.diagnostics]
        assert "sim.stdout.json_tail" in codes

    def test_run_traceback_probe(self):
        """PythonTracebackProbe detects unhandled exceptions in stderr."""
        code = textwrap.dedent("""
            raise ValueError("intentional error for test")
        """)
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(code)
            tmp = Path(f.name)
        try:
            result = execute_script(tmp, solver="test")
        finally:
            tmp.unlink()
        codes = [d["code"] for d in result.diagnostics]
        assert "python.ValueError" in codes

    def test_run_diagnostics_in_to_dict(self):
        """diagnostics and artifacts appear in RunResult.to_dict()."""
        result = execute_script(FIXTURES / "mock_solver.py")
        d = result.to_dict()
        assert "diagnostics" in d
        assert "artifacts" in d
        assert isinstance(d["diagnostics"], list)


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
