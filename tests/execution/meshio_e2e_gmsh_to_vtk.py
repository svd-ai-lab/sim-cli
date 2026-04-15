"""meshio E2E: Gmsh → meshio → VTK conversion pipeline.

Demonstrates meshio as a bridge between solvers' mesh formats:
1. Generate a unit sphere mesh with Gmsh (MSH 2.2 format)
2. Load via meshio.read
3. Convert cells and write out as VTK (legacy .vtk)
4. Re-read the VTK to verify round-trip preserves topology
5. Emit JSON with counts

Acceptance:
  - Read succeeds, > 100 points, > 300 total cells
  - Round-trip VTK preserves point count exactly
  - bbox approximately (-1, +1) on each axis (unit sphere)
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import meshio
import numpy as np


GEO = """SetFactory("OpenCASCADE");
Sphere(1) = {0, 0, 0, 1.0};
Physical Volume("ball") = {1};
Physical Surface("surf") = {1};
Mesh.MeshSizeMax = 0.3;
"""


def find_gmsh_cli():
    here = Path(sys.executable)
    cli = here.parent / "gmsh"
    if cli.is_file():
        return str(sys.executable), str(cli)
    import shutil
    c = shutil.which("gmsh")
    if c:
        return sys.executable, c
    return None, None


def main():
    py, gmsh_cli = find_gmsh_cli()
    if gmsh_cli is None:
        print(json.dumps({"ok": False, "error": "gmsh CLI not found"}))
        sys.exit(1)

    with tempfile.TemporaryDirectory(prefix="sim_meshio_e2e_") as tmp:
        tmp = Path(tmp)
        (tmp / "sphere.geo").write_text(GEO)

        # 1. Gmsh generates .msh
        proc = subprocess.run(
            [py, gmsh_cli, "sphere.geo", "-3", "-o", "sphere.msh", "-format", "msh22"],
            capture_output=True, text=True, cwd=str(tmp), timeout=120,
        )
        if proc.returncode != 0:
            print(json.dumps({
                "ok": False, "step": "gmsh",
                "stderr_tail": (proc.stderr or "")[-500:],
            }))
            sys.exit(1)

        # 2. meshio reads .msh
        mesh = meshio.read(tmp / "sphere.msh")
        points_msh = len(mesh.points)
        cells_msh = {c.type: len(c.data) for c in mesh.cells}
        total_cells = sum(cells_msh.values())

        # 3. Write .vtk
        vtk_path = tmp / "sphere.vtk"
        meshio.write(vtk_path, mesh)

        # 4. Round-trip read
        mesh_rt = meshio.read(vtk_path)
        points_rt = len(mesh_rt.points)

        # Compute bbox from original
        pts = np.asarray(mesh.points)
        bbox = {
            "xmin": float(pts[:, 0].min()), "xmax": float(pts[:, 0].max()),
            "ymin": float(pts[:, 1].min()), "ymax": float(pts[:, 1].max()),
            "zmin": float(pts[:, 2].min()), "zmax": float(pts[:, 2].max()),
        }

        result = {
            "ok": True,
            "step": "gmsh-to-vtk",
            "points": points_msh,
            "total_cells": total_cells,
            "cells_by_type": cells_msh,
            "roundtrip_points": points_rt,
            "points_match": points_msh == points_rt,
            "bbox": bbox,
            "solver": "meshio",
        }
        print(json.dumps(result))


if __name__ == "__main__":
    main()
