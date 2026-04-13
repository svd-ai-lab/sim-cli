"""Tier 4: Real Abaqus end-to-end test — cantilever beam.

Requires Abaqus installed. Skip-safe when not available.
Physics acceptance: tip deflection in 1e-7 to 1e-4 m range
(analytical ~2e-5 m, coarse 4-element CPS4 mesh gives ~5.75e-6 m).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

EXECUTION_DIR = Path(__file__).parent.parent.parent / "execution" / "abaqus"


def _abaqus_available() -> bool:
    try:
        from sim.drivers.abaqus import AbaqusDriver
        return AbaqusDriver().connect().status == "ok"
    except Exception:
        return False


_skip_no_abaqus = pytest.mark.skipif(
    not _abaqus_available(),
    reason="Abaqus not installed on this host",
)


@_skip_no_abaqus
@pytest.mark.integration
class TestAbaqusCantilever:
    """Real Abaqus E2E: cantilever beam under tip load."""

    def test_e2e_cantilever_run(self):
        """Run the cantilever E2E script and validate physics results."""
        script = EXECUTION_DIR / "abaqus_e2e_cantilever_run.py"
        assert script.is_file(), f"E2E script not found: {script}"

        proc = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert proc.returncode == 0, f"Script failed: {proc.stderr[:500]}"

        # Parse the last JSON line from stdout
        result = None
        for line in reversed(proc.stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    result = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue

        assert result is not None, f"No JSON output found in: {proc.stdout[:500]}"
        assert result["ok"] is True, f"Abaqus run failed: {result}"

        # Physics-based acceptance: tip deflection
        # Analytical: PL^3/(3EI) = 1000*10^3/(3*200e9*1/12) ~ 2e-5 m
        # FEM with coarse 4-element CPS4 mesh: observed 5.75e-6 m
        # Range: 1e-7 to 1e-4 m — wide enough for mesh/version tolerance,
        # narrow enough to catch gross errors (wrong BCs, wrong material)
        tip_deflection = result["tip_deflection_m"]
        assert 1e-7 < tip_deflection < 1e-4, (
            f"Tip deflection {tip_deflection:.3e} m outside plausible range "
            f"(expected ~5.75e-6 m for coarse mesh, analytical ~2e-5 m)"
        )

    def test_inp_lint_passes(self):
        """The .inp input deck passes lint."""
        from sim.drivers.abaqus import AbaqusDriver

        driver = AbaqusDriver()
        inp = EXECUTION_DIR / "abaqus_e2e_cantilever.inp"
        assert inp.is_file()

        result = driver.lint(inp)
        assert result.ok is True

    def test_inp_detect(self):
        """The .inp input deck is detected as Abaqus."""
        from sim.drivers.abaqus import AbaqusDriver

        driver = AbaqusDriver()
        inp = EXECUTION_DIR / "abaqus_e2e_cantilever.inp"
        assert driver.detect(inp) is True
