"""Tier 4: Real CalculiX E2E — cantilever beam.

Requires ccx installed. Skip-safe when not available.
Physics: analytical PL^3/(3EI) ~ 2000 (deck units), acceptance 500..5000.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _calculix_available() -> bool:
    try:
        from sim.drivers.calculix import CalculixDriver
        return CalculixDriver().connect().status == "ok"
    except Exception:
        return False


_skip_no_cx = pytest.mark.skipif(
    not _calculix_available(),
    reason="CalculiX (ccx) not installed",
)

EXECUTION_DIR = Path(__file__).parent.parent.parent / "execution"


@_skip_no_cx
@pytest.mark.integration
class TestCalculixCantilever:
    def test_e2e_cantilever_run(self):
        script = EXECUTION_DIR / "calculix_e2e_cantilever_run.py"
        assert script.is_file(), f"Missing E2E script: {script}"

        proc = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, timeout=180,
        )
        assert proc.returncode == 0, f"E2E script failed: {proc.stderr[:500]}"

        result = None
        for line in reversed(proc.stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    result = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
        assert result is not None, f"No JSON output: {proc.stdout[:500]}"
        assert result["ok"] is True, f"Run failed: {result}"
        assert result["tip_node"] == 3

        # Physics: analytical PL^3/(3EI) for beam=10, RECT 0.1x0.1,
        # E=200000, P=10 → delta ~ 2000 (deck units).
        tip_abs = result["tip_deflection_abs"]
        assert 500 < tip_abs < 5000, (
            f"tip_deflection_abs {tip_abs} outside 500..5000 "
            f"(analytical ~2000 for coarse 3-node B32R beam)"
        )

        # Sign: load is -Y, deflection should be negative in Y
        assert result["U2"] < 0, f"Tip U2 should be negative under -Y load, got {result['U2']}"

    def test_inp_lint_passes(self):
        from sim.drivers.calculix import CalculixDriver
        driver = CalculixDriver()
        fixture = Path(__file__).parent.parent.parent / "fixtures" / "calculix_good.inp"
        assert fixture.is_file()
        assert driver.lint(fixture).ok is True

    def test_inp_detect(self):
        from sim.drivers.calculix import CalculixDriver
        driver = CalculixDriver()
        fixture = Path(__file__).parent.parent.parent / "fixtures" / "calculix_good.inp"
        assert driver.detect(fixture) is True
