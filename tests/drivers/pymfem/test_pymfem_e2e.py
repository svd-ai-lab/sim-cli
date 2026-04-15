"""Tier 4: Real PyMFEM E2E — Poisson on unit square."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _available() -> bool:
    try:
        from sim.drivers.pymfem import PymfemDriver
        return PymfemDriver().connect().status == "ok"
    except Exception:
        return False


_skip = pytest.mark.skipif(not _available(), reason="pymfem not installed")

EXECUTION_DIR = Path(__file__).parent.parent.parent / "execution"


@_skip
@pytest.mark.integration
class TestPymfemPoisson:
    def test_e2e_poisson(self):
        script = EXECUTION_DIR / "pymfem_e2e_poisson.py"
        assert script.is_file()

        proc = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, timeout=120,
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

        # Poisson u_max for -Δu=1 on unit square is 0.073671
        u_max = result["u_max"]
        assert 0.06 < u_max < 0.09, (
            f"u_max={u_max} outside [0.06, 0.09] (analytical 0.0737)"
        )
        assert result["relative_error"] < 0.02, (
            f"Relative error {result['relative_error']*100:.2f}% exceeds 2%"
        )

    def test_py_lint(self):
        from sim.drivers.pymfem import PymfemDriver
        d = PymfemDriver()
        fx = Path(__file__).parent.parent.parent / "fixtures" / "mfem_good.py"
        assert d.lint(fx).ok is True

    def test_py_detect(self):
        from sim.drivers.pymfem import PymfemDriver
        d = PymfemDriver()
        fx = Path(__file__).parent.parent.parent / "fixtures" / "mfem_good.py"
        assert d.detect(fx) is True
