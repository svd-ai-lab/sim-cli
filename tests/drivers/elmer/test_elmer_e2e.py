"""Tier 4: Real Elmer FEM E2E — heat conduction on unit square."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _elmer_available() -> bool:
    try:
        from sim.drivers.elmer import ElmerDriver
        return ElmerDriver().connect().status == "ok"
    except Exception:
        return False


_skip_no_elmer = pytest.mark.skipif(
    not _elmer_available(),
    reason="Elmer FEM not installed",
)

EXECUTION_DIR = Path(__file__).parent.parent.parent / "execution"


@_skip_no_elmer
@pytest.mark.integration
class TestElmerHeatSquare:
    def test_e2e_heat_square(self):
        script = EXECUTION_DIR / "elmer_e2e_heat_square.py"
        assert script.is_file()

        proc = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, timeout=600,
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

        # Physics acceptance
        # Analytical: max T for -ΔT=1, T=0 on unit square is ≈ 0.0737
        # 10x10 quad mesh gives ~1% error
        max_t = result["max_temperature"]
        assert max_t is not None
        assert 0.05 < max_t < 0.10, (
            f"max_temperature {max_t} outside [0.05, 0.10] "
            f"(analytical 0.0737)"
        )
        assert result["relative_error"] < 0.05, (
            f"Relative error {result['relative_error']*100:.2f}% exceeds 5%"
        )

        # Mesh shape
        assert result["nodes"] == 121  # 11x11 grid
        assert result["elements"] == 100  # 10x10 quads

    def test_sif_lint_passes(self):
        from sim.drivers.elmer import ElmerDriver
        driver = ElmerDriver()
        fixture = Path(__file__).parent.parent.parent / "fixtures" / "elmer_good.sif"
        assert driver.lint(fixture).ok is True

    def test_sif_detect(self):
        from sim.drivers.elmer import ElmerDriver
        driver = ElmerDriver()
        fixture = Path(__file__).parent.parent.parent / "fixtures" / "elmer_good.sif"
        assert driver.detect(fixture) is True
