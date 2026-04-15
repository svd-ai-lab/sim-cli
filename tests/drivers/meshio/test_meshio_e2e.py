"""Tier 4: Real meshio E2E — Gmsh → meshio → VTK format conversion pipeline."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _meshio_and_gmsh_available() -> bool:
    try:
        from sim.drivers.meshio import MeshioDriver
        from sim.drivers.gmsh import GmshDriver
        return (MeshioDriver().connect().status == "ok"
                and GmshDriver().connect().status == "ok")
    except Exception:
        return False


_skip = pytest.mark.skipif(
    not _meshio_and_gmsh_available(),
    reason="meshio or gmsh not available",
)

EXECUTION_DIR = Path(__file__).parent.parent.parent / "execution"


@_skip
@pytest.mark.integration
class TestMeshioGmshToVtk:
    def test_e2e_conversion(self):
        script = EXECUTION_DIR / "meshio_e2e_gmsh_to_vtk.py"
        assert script.is_file()

        proc = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, timeout=180,
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

        # Topology
        assert result["points"] > 100, f"points={result['points']} too few"
        assert result["total_cells"] > 300, f"cells={result['total_cells']} too few"
        assert result["points_match"] is True, "VTK round-trip lost points"

        # bbox of unit sphere mesh should be close to ±1
        bbox = result["bbox"]
        assert abs(bbox["xmax"] - 1.0) < 0.05
        assert abs(bbox["xmin"] + 1.0) < 0.05

    def test_py_lint(self):
        from sim.drivers.meshio import MeshioDriver
        driver = MeshioDriver()
        fx = Path(__file__).parent.parent.parent / "fixtures" / "meshio_good.py"
        assert driver.lint(fx).ok is True

    def test_py_detect(self):
        from sim.drivers.meshio import MeshioDriver
        driver = MeshioDriver()
        fx = Path(__file__).parent.parent.parent / "fixtures" / "meshio_good.py"
        assert driver.detect(fx) is True
