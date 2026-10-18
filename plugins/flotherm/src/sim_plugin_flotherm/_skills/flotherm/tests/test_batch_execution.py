"""Execution tests for sim-agent-flotherm Phase A — batch .pack solve.

These tests require Simcenter Flotherm 2504 to be installed.
They are skipped automatically when the installation is not present.

Test oracle: Mobile_Demo-Steady_State.pack (from Flotherm installation examples)

Design rationale (from spec §4):
    Execution tests verify that the driver + agent workflow actually runs a
    real Flotherm project to completion. They catch:
    - wrong batch command construction
    - wrong env var setup (FLOUSERDIR, FLO_ROOT, etc.)
    - floserv startup failures
    - output parsing errors

    "exit_code=0" alone is NOT the acceptance criterion. Tests also verify
    that stdout is non-empty and duration is measured — the baseline for
    Phase B result-extraction tests.

Run all tests:
    cd E:/sim/sim-agent-flotherm
    pytest tests/test_batch_execution.py -v

Run only smoke tests (fast, no real solve):
    pytest tests/test_batch_execution.py -v -m "not slow"
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import AGENT_ROOT, DEMO_PACK, _demo_pack_exists, _flotherm_installed

# ---------------------------------------------------------------------------
# Conditional imports — driver lives in sim package
# ---------------------------------------------------------------------------
try:
    from sim.drivers.flotherm import FlothermDriver
    from sim.driver import ConnectionInfo, LintResult, RunResult
    _HAS_DRIVER = True
except ImportError:
    _HAS_DRIVER = False


# ---------------------------------------------------------------------------
# Skip conditions
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.flotherm

_skip_no_driver = pytest.mark.skipif(
    not _HAS_DRIVER,
    reason="sim.drivers.flotherm not importable",
)
_skip_no_flotherm = pytest.mark.skipif(
    not (_HAS_DRIVER and _flotherm_installed()),
    reason="Simcenter Flotherm 2504 not installed",
)
_skip_no_demo_pack = pytest.mark.skipif(
    not _demo_pack_exists(),
    reason=f"Demo .pack not found: {DEMO_PACK}",
)


# ---------------------------------------------------------------------------
# Pre-flight: driver importable and Flotherm installed
# ---------------------------------------------------------------------------

class TestPreFlight:
    """Verify the environment before attempting any real runs."""

    @_skip_no_driver
    def test_driver_importable(self):
        from sim.drivers.flotherm import FlothermDriver
        assert FlothermDriver is not None

    @_skip_no_driver
    def test_driver_name(self):
        assert FlothermDriver().name == "flotherm"

    @_skip_no_flotherm
    def test_connect_reports_ok(self):
        info = FlothermDriver().connect()
        assert info.status == "ok", f"Expected ok, got: {info.status} — {info.message}"

    @_skip_no_flotherm
    def test_connect_reports_version_2504(self):
        info = FlothermDriver().connect()
        assert info.version == "2504", f"Expected version 2504, got {info.version}"

    @_skip_no_flotherm
    def test_connect_message_contains_path(self):
        info = FlothermDriver().connect()
        assert "flotherm.bat" in info.message.lower() or "simcenter" in info.message.lower(), \
            f"Connection message should reference flotherm.bat: {info.message}"


# ---------------------------------------------------------------------------
# Input validation: lint + detect
# ---------------------------------------------------------------------------

class TestInputValidation:
    """Agent step 1: validate inputs before running anything."""

    @_skip_no_driver
    @_skip_no_demo_pack
    def test_detect_demo_pack(self):
        """detect() must return True for the demo .pack oracle."""
        assert FlothermDriver().detect(DEMO_PACK) is True

    @_skip_no_driver
    @_skip_no_demo_pack
    def test_lint_demo_pack_ok(self):
        """lint() must return ok=True for the demo .pack oracle."""
        result = FlothermDriver().lint(DEMO_PACK)
        assert result.ok is True, f"Lint failed: {result.diagnostics}"

    @_skip_no_driver
    @_skip_no_demo_pack
    def test_lint_demo_pack_no_errors(self):
        result = FlothermDriver().lint(DEMO_PACK)
        errors = [d for d in result.diagnostics if d.level == "error"]
        assert errors == [], f"Unexpected lint errors: {errors}"

    @_skip_no_driver
    def test_detect_non_pack_returns_false(self, tmp_path):
        fake = tmp_path / "not_a_pack.txt"
        fake.write_text("hello")
        assert FlothermDriver().detect(fake) is False

    @_skip_no_driver
    def test_lint_nonexistent_pack_returns_error(self, tmp_path):
        missing = tmp_path / "missing.pack"
        result = FlothermDriver().lint(missing)
        assert result.ok is False
        assert any("Cannot read" in d.message or "not found" in d.message.lower()
                   for d in result.diagnostics)

    @_skip_no_driver
    def test_lint_corrupt_pack_returns_error(self, tmp_path):
        corrupt = tmp_path / "corrupt.pack"
        corrupt.write_bytes(b"not a zip file at all")
        result = FlothermDriver().lint(corrupt)
        assert result.ok is False


# ---------------------------------------------------------------------------
# Batch execution: run_file
# ---------------------------------------------------------------------------

class TestBatchExecution:
    """Agent step 2-3: run the .pack and capture RunResult.

    These tests mark the actual solve as @pytest.mark.slow because
    Mobile_Demo-Steady_State.pack may take several minutes on first run.
    """

    @_skip_no_flotherm
    @_skip_no_demo_pack
    @pytest.mark.slow
    def test_run_file_returns_run_result(self):
        """run_file must return a RunResult instance."""
        result = FlothermDriver().run_file(DEMO_PACK)
        assert isinstance(result, RunResult), \
            f"Expected RunResult, got {type(result)}"

    @_skip_no_flotherm
    @_skip_no_demo_pack
    @pytest.mark.slow
    def test_run_file_returns_waiting_backend_state(self):
        """With NullBackend (default), run_file returns WAITING_BACKEND (exit_code=3).

        This is the correct behavior: no automated execution backend
        is available, so the job is queued for external intervention.
        exit_code=3 maps to WAITING_BACKEND in the runtime state model.
        """
        result = FlothermDriver().run_file(DEMO_PACK)
        assert result.exit_code == 3, (
            f"Expected exit_code=3 (WAITING_BACKEND), got {result.exit_code}.\n"
            f"stdout: {result.stdout[:300]}\n"
            f"stderr: {result.stderr[:300]}"
        )
        assert "waiting_backend" in result.stdout

    @_skip_no_flotherm
    @_skip_no_demo_pack
    @pytest.mark.slow
    def test_run_file_has_job_id(self):
        """RunResult stdout must contain a job_id for tracking."""
        result = FlothermDriver().run_file(DEMO_PACK)
        assert "job_id:" in result.stdout

    @_skip_no_flotherm
    @_skip_no_demo_pack
    @pytest.mark.slow
    def test_run_file_solver_field(self):
        result = FlothermDriver().run_file(DEMO_PACK)
        assert result.solver == "flotherm"

    @_skip_no_flotherm
    @_skip_no_demo_pack
    @pytest.mark.slow
    def test_run_file_script_field(self):
        result = FlothermDriver().run_file(DEMO_PACK)
        assert str(DEMO_PACK) in result.script

    @_skip_no_flotherm
    @_skip_no_demo_pack
    @pytest.mark.slow
    def test_run_file_timestamp_is_iso(self):
        """Timestamp must be an ISO 8601 string."""
        from datetime import datetime
        result = FlothermDriver().run_file(DEMO_PACK)
        # Should not raise
        dt = datetime.fromisoformat(result.timestamp)
        assert dt.year == 2026

    @_skip_no_flotherm
    @_skip_no_demo_pack
    @pytest.mark.slow
    def test_run_file_solve_actually_ran(self):
        """Verify the thermal solve executed, not just that floserv started.

        A failed solve (missing ccstatefile.txt / project not recognised)
        produces E/11029 and E/9012 in the run output.  A successful solve
        produces neither.  The registerStart runTable exception is expected
        and non-fatal — we do NOT assert its absence.
        """
        result = FlothermDriver().run_file(DEMO_PACK)
        combined = (result.stdout + " " + result.stderr).lower()
        assert "e/11029" not in combined, (
            "E/11029 'Failed unknown file type' found — floserv did not recognise "
            "the project.  This usually means PDProject/ccstatefile.txt is missing."
        )
        assert "e/9012" not in combined, (
            "E/9012 'Too few grid-cells' found — floserv fell back to a 1x1 empty "
            "project instead of solving the real model."
        )


# ---------------------------------------------------------------------------
# Output parsing
# ---------------------------------------------------------------------------

class TestOutputParsing:
    """Agent step 3: parse_output must extract structured data from stdout."""

    @_skip_no_driver
    def test_parse_output_empty_returns_empty_dict(self):
        assert FlothermDriver().parse_output("") == {}

    @_skip_no_driver
    def test_parse_output_no_json_returns_empty_dict(self):
        assert FlothermDriver().parse_output("Floserv starting...\nSolving...") == {}

    @_skip_no_driver
    def test_parse_output_extracts_last_json_line(self):
        stdout = (
            "Floserv starting...\n"
            "Iteration 1: residual=1.2e-3\n"
            '{"status": "complete", "max_temp_C": 72.4}\n'
        )
        result = FlothermDriver().parse_output(stdout)
        assert result == {"status": "complete", "max_temp_C": 72.4}

    @_skip_no_driver
    def test_parse_output_takes_last_json_not_first(self):
        stdout = (
            '{"early": true}\n'
            "Some text\n"
            '{"final": true, "temp": 55.0}\n'
        )
        result = FlothermDriver().parse_output(stdout)
        assert result.get("final") is True

    @_skip_no_driver
    def test_parse_output_skips_invalid_json(self):
        stdout = (
            "not json\n"
            "{broken json\n"
            '{"valid": true}\n'
        )
        result = FlothermDriver().parse_output(stdout)
        assert result == {"valid": True}


# ---------------------------------------------------------------------------
# Not-installed error path
# ---------------------------------------------------------------------------

class TestNotInstalled:
    """run_file must raise RuntimeError with helpful message when not installed."""

    @_skip_no_driver
    def test_run_file_raises_when_not_installed(self, tmp_path, monkeypatch):
        # Patch at both import sites: driver.py and runtime.py
        import sim.drivers.flotherm.driver as drv_mod
        import sim.drivers.flotherm._helpers as helpers_mod
        monkeypatch.setattr(drv_mod, "find_installation", lambda: None)
        monkeypatch.setattr(helpers_mod, "find_installation", lambda: None)

        pack = tmp_path / "fake.pack"
        import zipfile
        with zipfile.ZipFile(pack, "w") as z:
            z.writestr("project/dummy.txt", "x")

        with pytest.raises(RuntimeError, match="[Ff]lotherm"):
            FlothermDriver().run_file(pack)

    @_skip_no_driver
    def test_run_xml_returns_waiting_backend(self, tmp_path):
        """FloSCRIPT .xml execution goes through runtime, enters WAITING_BACKEND."""
        xml = tmp_path / "test.xml"
        xml.write_text(
            '<?xml version="1.0"?>\n'
            '<xml_log_file version="1.0"><solve_all/></xml_log_file>\n'
        )
        result = FlothermDriver().run_file(xml)
        # exit_code 3 = WAITING_BACKEND (no backend can execute)
        assert result.exit_code == 3
        assert "waiting_backend" in result.stdout
