"""Tier 4: Real scikit-fem E2E — Poisson equation on unit square."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _skfem_available() -> bool:
    try:
        from sim.drivers.scikit_fem import ScikitFemDriver
        return ScikitFemDriver().connect().status == "ok"
    except Exception:
        return False


_skip_no_skfem = pytest.mark.skipif(
    not _skfem_available(),
    reason="scikit-fem not importable",
)

EXECUTION_DIR = Path(__file__).parent.parent.parent / "execution"


@_skip_no_skfem
@pytest.mark.integration
class TestScikitFemPoisson:
    def test_e2e_poisson(self):
        script = EXECUTION_DIR / "scikit_fem_e2e_poisson.py"
        assert script.is_file()

        proc = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, timeout=60,
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
        assert result["ok"] is True

        # Physics acceptance
        # Analytical u_max for -Δu=1 on unit square with Dirichlet 0 is 0.0736713
        # FEM should match within 2% on refined mesh
        u_max = result["u_max"]
        assert 0.05 < u_max < 0.10, (
            f"u_max={u_max} outside plausible range [0.05, 0.10] "
            f"(analytical=0.0737)"
        )
        assert result["relative_error"] < 0.02, (
            f"Relative error {result['relative_error']*100:.2f}% exceeds 2%"
        )

        # Maximum should be near center (0.5, 0.5) by symmetry
        xm, ym = result["u_max_location"]
        assert abs(xm - 0.5) < 0.1 and abs(ym - 0.5) < 0.1, (
            f"u_max at ({xm}, {ym}) — expected near (0.5, 0.5)"
        )

    def test_py_lint_passes(self):
        from sim.drivers.scikit_fem import ScikitFemDriver
        driver = ScikitFemDriver()
        fixture = Path(__file__).parent.parent.parent / "fixtures" / "skfem_good.py"
        assert driver.lint(fixture).ok is True

    def test_py_detect(self):
        from sim.drivers.scikit_fem import ScikitFemDriver
        driver = ScikitFemDriver()
        fixture = Path(__file__).parent.parent.parent / "fixtures" / "skfem_good.py"
        assert driver.detect(fixture) is True
