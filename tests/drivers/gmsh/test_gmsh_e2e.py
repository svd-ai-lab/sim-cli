"""Tier 4: Real Gmsh E2E — unit sphere mesh generation.

Requires gmsh importable. Skip-safe when not available.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _gmsh_available() -> bool:
    try:
        from sim.drivers.gmsh import GmshDriver
        return GmshDriver().connect().status == "ok"
    except Exception:
        return False


_skip_no_gmsh = pytest.mark.skipif(
    not _gmsh_available(),
    reason="Gmsh not importable",
)

EXECUTION_DIR = Path(__file__).parent.parent.parent / "execution"


@_skip_no_gmsh
@pytest.mark.integration
class TestGmshSphereMesh:
    def test_e2e_sphere_mesh(self):
        script = EXECUTION_DIR / "gmsh_e2e_sphere_mesh.py"
        assert script.is_file(), f"Missing E2E: {script}"

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
        assert result["ok"] is True, f"Run failed: {result}"

        # Topology-based acceptance (analogous to physics):
        # Sphere r=1.0, mesh size 0.3 → typical 258 nodes, 1291 elems
        assert 100 < result["nodes"] < 2000, f"nodes={result['nodes']} out of range"
        assert 300 < result["elements"] < 5000, f"elements={result['elements']} out of range"

        # Bounding box should be approximately ±1 (unit sphere)
        bbox = result["bbox"]
        assert abs(bbox["xmax"] - 1.0) < 0.05, f"xmax={bbox['xmax']}"
        assert abs(bbox["xmin"] + 1.0) < 0.05, f"xmin={bbox['xmin']}"

    def test_geo_lint_passes(self):
        from sim.drivers.gmsh import GmshDriver
        driver = GmshDriver()
        fixture = Path(__file__).parent.parent.parent / "fixtures" / "gmsh_good.geo"
        assert driver.lint(fixture).ok is True

    def test_geo_detect(self):
        from sim.drivers.gmsh import GmshDriver
        driver = GmshDriver()
        fixture = Path(__file__).parent.parent.parent / "fixtures" / "gmsh_good.geo"
        assert driver.detect(fixture) is True
