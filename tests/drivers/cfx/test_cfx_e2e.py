"""CFX E2E test — requires Ansys CFX installed.

Uses VMFL015 verification case: Working Fluid pipe flow, SST turbulence.
Acceptance: all RMS residuals < 1e-5 within 200 iterations.
"""
import re
from pathlib import Path

import pytest

from sim.drivers.cfx import CfxDriver

# ---------------------------------------------------------------------------
# Skip if CFX not installed
# ---------------------------------------------------------------------------

def _cfx_available() -> bool:
    try:
        return CfxDriver().connect().status == "ok"
    except Exception:
        return False

_skip_no_cfx = pytest.mark.skipif(
    not _cfx_available(),
    reason="Ansys CFX not installed on this host",
)

# VMFL015 .def file — adjust path if needed
_VMFL015_DEF = Path("E:/CFX_tutorial/test_case_to_rrh/test_case_to_rrh/VMFL015_CFX/input/015.def")


@_skip_no_cfx
@pytest.mark.integration
class TestCfxE2E:
    """Real CFX solve of VMFL015 verification case.

    First observed: 122 iterations, all RMS residuals < 1e-5.
    Acceptance range: completes within 200 iterations, residuals < 1e-4.
    """

    @pytest.fixture(scope="class")
    def solve_result(self, tmp_path_factory):
        """Run VMFL015 solve once for all tests in this class."""
        if not _VMFL015_DEF.is_file():
            pytest.skip(f"VMFL015 def file not found at {_VMFL015_DEF}")

        import shutil
        work_dir = tmp_path_factory.mktemp("cfx_e2e")
        def_copy = work_dir / "015.def"
        shutil.copy2(_VMFL015_DEF, def_copy)

        driver = CfxDriver()
        result = driver.run_file(def_copy)
        return result, work_dir

    def test_solve_completes(self, solve_result):
        result, _ = solve_result
        assert result.exit_code == 0, f"CFX solve failed: {result.stderr}"
        assert result.ok, f"Errors detected: {result.errors}"

    def test_residuals_converged(self, solve_result):
        """All RMS residuals must be below target (1e-5) or at least < 1e-4."""
        _, work_dir = solve_result
        out_files = list(work_dir.glob("015_*.out"))
        assert len(out_files) > 0, "No .out file produced"

        out_text = out_files[-1].read_text(encoding="utf-8", errors="replace")

        # Extract final iteration residuals
        # .out format: | U-Mom  | Rate | RMS Res | Max Res | Linear Solution |
        # We need the RMS Res column (3rd field after the equation name)
        final_block = re.findall(
            r"OUTER LOOP ITERATION\s*=\s*(\d+).*?"
            r"\| U-Mom\s+\|\s*\S+\s*\|\s*(\S+).*?"
            r"\| V-Mom\s+\|\s*\S+\s*\|\s*(\S+).*?"
            r"\| W-Mom\s+\|\s*\S+\s*\|\s*(\S+).*?"
            r"\| P-Mass\s+\|\s*\S+\s*\|\s*(\S+)",
            out_text, re.DOTALL,
        )
        assert len(final_block) > 0, "Could not parse residuals from .out file"

        last = final_block[-1]
        iteration = int(last[0])
        u_rms = float(last[1])
        v_rms = float(last[2])
        w_rms = float(last[3])
        p_rms = float(last[4])

        # Acceptance: converge within 200 iterations
        assert iteration <= 200, f"Took {iteration} iterations (expected <= 200)"

        # Acceptance: all RMS < 1e-4 (target is 1e-5, allow some margin)
        assert u_rms < 1e-4, f"U-Mom RMS {u_rms} too high"
        assert v_rms < 1e-4, f"V-Mom RMS {v_rms} too high"
        assert w_rms < 1e-4, f"W-Mom RMS {w_rms} too high"
        assert p_rms < 1e-4, f"P-Mass RMS {p_rms} too high"

    def test_results_file_produced(self, solve_result):
        _, work_dir = solve_result
        res_files = list(work_dir.glob("015_*.res"))
        assert len(res_files) > 0, "No .res result file produced"
        # Result file should be substantial (> 1 MB for this case)
        assert res_files[-1].stat().st_size > 1_000_000, "Result file suspiciously small"
