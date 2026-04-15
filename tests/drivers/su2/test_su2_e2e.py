"""Tier 4: Real SU2 E2E — Inviscid Bump Euler flow (convergence-based).

Requires SU2_CFD + Tutorials clone. Skip-safe.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _su2_available() -> bool:
    try:
        from sim.drivers.su2 import Su2Driver
        return Su2Driver().connect().status == "ok"
    except Exception:
        return False


_TUTORIAL = Path("/data/Chenyx/sim/refs/Tutorials/compressible_flow/Inviscid_Bump/inv_channel.cfg")


_skip_no_su2 = pytest.mark.skipif(
    not _su2_available() or not _TUTORIAL.is_file(),
    reason="SU2 not installed or Tutorials not cloned",
)

EXECUTION_DIR = Path(__file__).parent.parent.parent / "execution"


@_skip_no_su2
@pytest.mark.integration
class TestSu2InviscidBump:
    def test_e2e_inviscid_bump(self):
        script = EXECUTION_DIR / "su2_e2e_inviscid_bump.py"
        assert script.is_file()

        proc = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, timeout=1200,
        )
        assert proc.returncode == 0, f"E2E failed: {proc.stderr[:500]}"

        result = None
        for line in reversed(proc.stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    result = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
        assert result is not None, f"No JSON: {proc.stdout[:500]}"
        assert result["ok"] is True, f"Failed: {result}"

        # At least 80 iterations completed of the 100 requested
        assert result["n_iterations"] >= 80, (
            f"Only {result['n_iterations']} iterations recorded"
        )

        # Residual dropped from ~-1.4 to at least -2 (1 order of magnitude)
        final = result["final_rms_rho"]
        assert final is not None, "final_rms_rho not parsed from history.csv"
        assert final < -2.0, (
            f"RMS[Rho] final {final:.3f} did not drop below -2 "
            f"— solver not converging"
        )

    def test_cfg_lint_passes(self):
        from sim.drivers.su2 import Su2Driver
        driver = Su2Driver()
        fixture = Path(__file__).parent.parent.parent / "fixtures" / "su2_good.cfg"
        assert driver.lint(fixture).ok is True

    def test_cfg_detect(self):
        from sim.drivers.su2 import Su2Driver
        driver = Su2Driver()
        fixture = Path(__file__).parent.parent.parent / "fixtures" / "su2_good.cfg"
        assert driver.detect(fixture) is True
