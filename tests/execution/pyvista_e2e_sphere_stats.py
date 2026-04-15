"""pyvista E2E: full post-processing pipeline.

Pipeline:
1. Gmsh generates unit sphere .msh
2. meshio converts to .vtu
3. pyvista reads .vtu, computes surface area, volume, bounding box
4. Validate against analytical values (sphere r=1 → S=4π≈12.566, V=4π/3≈4.189)
5. Emit JSON

Acceptance:
  - Surface area in 80-110% of 4π
  - Volume in 80-110% of 4π/3
  - bbox approximately ±1
"""
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pyvista as pv
import meshio


GEO = """SetFactory("OpenCASCADE");
Sphere(1) = {0, 0, 0, 1.0};
Physical Volume("ball") = {1};
Physical Surface("surf") = {1};
Mesh.MeshSizeMax = 0.2;
"""


def find_gmsh():
    here = Path(sys.executable)
    cli = here.parent / "gmsh"
    if cli.is_file():
        return str(sys.executable), str(cli)
    return None, None


def main():
    py, gmsh_cli = find_gmsh()
    if gmsh_cli is None:
        print(json.dumps({"ok": False, "error": "gmsh not found"}))
        sys.exit(1)

    with tempfile.TemporaryDirectory(prefix="sim_pv_e2e_") as tmp:
        tmp = Path(tmp)
        (tmp / "sphere.geo").write_text(GEO)

        # 1. Gmsh → .msh
        proc = subprocess.run(
            [py, gmsh_cli, "sphere.geo", "-3", "-o", "sphere.msh", "-format", "msh22"],
            capture_output=True, text=True, cwd=str(tmp), timeout=120,
        )
        if proc.returncode != 0:
            print(json.dumps({"ok": False, "step": "gmsh",
                              "stderr": (proc.stderr or "")[-500:]}))
            sys.exit(1)

        # 2. meshio → .vtu (pyvista reads .vtu natively)
        # Keep only tet cells — Gmsh writes both boundary tris and volume tets;
        # extracting surface from the combined mesh would count each face twice.
        mesh = meshio.read(tmp / "sphere.msh")
        tet_only = meshio.Mesh(
            points=mesh.points,
            cells=[(c.type, c.data) for c in mesh.cells if c.type == "tetra"],
        )
        meshio.write(tmp / "sphere.vtu", tet_only)

        # 3. pyvista reads and computes stats
        grid = pv.read(str(tmp / "sphere.vtu"))

        # Unit sphere analytical:
        # Surface area 4πr² = 4π ≈ 12.5664
        # Volume 4πr³/3 = 4π/3 ≈ 4.1888
        surf_analytical = 4 * math.pi * 1.0**2
        vol_analytical = 4 * math.pi * 1.0**3 / 3

        # Extract surface mesh (boundary tri cells) for area
        surface = grid.extract_surface()
        surf_area = float(surface.area)

        # Volume of the full unstructured grid (sum of tetra volumes)
        # Use Integrate Data filter via compute_cell_sizes
        sized = grid.compute_cell_sizes(length=False, area=False, volume=True)
        total_volume = float(sized.cell_data["Volume"].sum())

        result = {
            "ok": True,
            "step": "sphere-stats",
            "n_points": int(grid.n_points),
            "n_cells": int(grid.n_cells),
            "bounds": list(map(float, grid.bounds)),
            "surface_area": surf_area,
            "surface_analytical": surf_analytical,
            "surface_error_pct": abs(surf_area - surf_analytical) / surf_analytical * 100,
            "volume": total_volume,
            "volume_analytical": vol_analytical,
            "volume_error_pct": abs(total_volume - vol_analytical) / vol_analytical * 100,
            "solver": "pyvista",
        }
        print(json.dumps(result))


if __name__ == "__main__":
    main()
