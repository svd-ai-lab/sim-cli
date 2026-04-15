"""Tier 4: Real pyvista E2E — Gmsh → meshio → pyvista post-processing pipeline."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _available() -> bool:
    try:
        from sim.drivers.pyvista import PyvistaDriver
        from sim.drivers.gmsh import GmshDriver
        from sim.drivers.meshio import MeshioDriver
        return (PyvistaDriver().connect().status == "ok"
                and GmshDriver().connect().status == "ok"
                and MeshioDriver().connect().status == "ok")
    except Exception:
        return False


_skip = pytest.mark.skipif(not _available(), reason="pyvista/gmsh/meshio missing")

EXECUTION_DIR = Path(__file__).parent.parent.parent / "execution"


@_skip
@pytest.mark.integration
class TestPyvistaSphereStats:
    def test_e2e_sphere_stats(self):
        script = EXECUTION_DIR / "pyvista_e2e_sphere_stats.py"
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
        assert result["ok"] is True

        # Analytical: surface 4π ≈ 12.566, volume 4π/3 ≈ 4.189
        # Tet mesh from Gmsh with MeshSize=0.2 should give < 10% error on both
        assert result["surface_error_pct"] < 15, (
            f"Surface area error {result['surface_error_pct']:.1f}% exceeds 15%"
        )
        assert result["volume_error_pct"] < 15, (
            f"Volume error {result['volume_error_pct']:.1f}% exceeds 15%"
        )

        # Bounds ≈ ±1
        xmin, xmax, ymin, ymax, zmin, zmax = result["bounds"]
        assert abs(xmax - 1.0) < 0.05 and abs(xmin + 1.0) < 0.05

    def test_py_lint(self):
        from sim.drivers.pyvista import PyvistaDriver
        d = PyvistaDriver()
        fx = Path(__file__).parent.parent.parent / "fixtures" / "pyvista_good.py"
        assert d.lint(fx).ok is True

    def test_py_detect(self):
        from sim.drivers.pyvista import PyvistaDriver
        d = PyvistaDriver()
        fx = Path(__file__).parent.parent.parent / "fixtures" / "pyvista_good.py"
        assert d.detect(fx) is True
