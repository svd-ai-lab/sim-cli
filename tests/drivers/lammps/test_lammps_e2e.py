"""Tier 4: Real LAMMPS E2E — LJ liquid NVT equilibration."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _lammps_available() -> bool:
    try:
        from sim.drivers.lammps import LammpsDriver
        return LammpsDriver().connect().status == "ok"
    except Exception:
        return False


_skip_no_lmp = pytest.mark.skipif(
    not _lammps_available(),
    reason="LAMMPS not installed",
)

EXECUTION_DIR = Path(__file__).parent.parent.parent / "execution"


@_skip_no_lmp
@pytest.mark.integration
class TestLammpsLjNvt:
    def test_e2e_lj_nvt(self):
        script = EXECUTION_DIR / "lammps_e2e_lj_nvt.py"
        assert script.is_file()

        proc = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, timeout=300,
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

        # Physics: Nose-Hoover at T=1.5 should land nearby after 50 steps
        final_temp = result["final_temp"]
        assert 0.5 < final_temp < 2.5, (
            f"Final temp {final_temp} outside 0.5..2.5 "
            f"(target=1.5, NVT Nose-Hoover tau=0.1)"
        )

        # Total energy must be finite (not NaN or infinite)
        etotal = result["final_etotal"]
        import math
        assert math.isfinite(etotal), f"Total energy {etotal} is not finite"

        assert result["final_step"] == 50

    def test_in_lint_passes(self):
        from sim.drivers.lammps import LammpsDriver
        driver = LammpsDriver()
        fixture = Path(__file__).parent.parent.parent / "fixtures" / "lammps_good.in"
        assert driver.lint(fixture).ok is True

    def test_in_detect(self):
        from sim.drivers.lammps import LammpsDriver
        driver = LammpsDriver()
        fixture = Path(__file__).parent.parent.parent / "fixtures" / "lammps_good.in"
        assert driver.detect(fixture) is True
