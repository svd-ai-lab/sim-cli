"""Gmsh E2E: generate a 3D mesh of a unit sphere and validate topology.

Run via: sim run tests/execution/gmsh_e2e_sphere_mesh.py --solver gmsh

Steps:
1. Write a .geo file defining a unit sphere (OpenCASCADE)
2. Run gmsh -3 to generate 3D tet mesh
3. Parse the .msh header for node/element counts
4. Emit JSON for sim to capture

Validation (topology-based, analogous to physics acceptance):
  Sphere radius 1.0, mesh size 0.3 →
    nodes:    100-500  (typical 258)
    elements: 300-3000 (typical 1291, includes volume tets + surface tris)
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

GEO_CONTENT = """SetFactory("OpenCASCADE");
Sphere(1) = {0, 0, 0, 1.0};
Physical Volume("ball") = {1};
Physical Surface("surf") = {1};
Mesh.MeshSizeMax = 0.3;
"""


def find_gmsh():
    """Return (python_exe, gmsh_cli_script) or (None, None)."""
    # Prefer the current interpreter's venv
    here = Path(sys.executable)
    cli = here.parent / "gmsh"
    if cli.is_file():
        return str(here), str(cli)
    # Fallback PATH
    import shutil
    cli = shutil.which("gmsh")
    if cli:
        cli_p = Path(cli).resolve()
        for name in ("python3", "python"):
            py = cli_p.parent / name
            if py.is_file():
                return str(py), str(cli_p)
        return sys.executable, str(cli_p)
    return None, None


def parse_msh(msh_path):
    """Parse $Nodes / $Elements counts + bbox from a msh2 file."""
    lines = msh_path.read_text(encoding="utf-8", errors="replace").splitlines()
    nodes = 0
    elements = 0
    xs = []
    ys = []
    zs = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line == "$Nodes":
            nodes = int(lines[i + 1].strip())
            for j in range(i + 2, i + 2 + nodes):
                parts = lines[j].split()
                if len(parts) >= 4:
                    xs.append(float(parts[1]))
                    ys.append(float(parts[2]))
                    zs.append(float(parts[3]))
            i += 2 + nodes
            continue
        if line == "$Elements":
            elements = int(lines[i + 1].strip())
            break
        i += 1
    bbox = None
    if xs:
        bbox = {
            "xmin": min(xs), "xmax": max(xs),
            "ymin": min(ys), "ymax": max(ys),
            "zmin": min(zs), "zmax": max(zs),
        }
    return {"nodes": nodes, "elements": elements, "bbox": bbox}


def main():
    python_exe, gmsh_cli = find_gmsh()
    if not python_exe or not gmsh_cli:
        print(json.dumps({"ok": False, "error": "gmsh CLI not found"}))
        sys.exit(1)

    with tempfile.TemporaryDirectory(prefix="sim_gmsh_e2e_") as tmp:
        tmp = Path(tmp)
        geo = tmp / "sphere.geo"
        geo.write_text(GEO_CONTENT, encoding="utf-8")

        out_msh = tmp / "sphere.msh"
        proc = subprocess.run(
            [python_exe, gmsh_cli, "sphere.geo", "-3",
             "-o", "sphere.msh", "-format", "msh22"],
            capture_output=True, text=True, cwd=str(tmp), timeout=120,
        )

        if proc.returncode != 0:
            print(json.dumps({
                "ok": False,
                "exit_code": proc.returncode,
                "stderr": (proc.stderr or "")[:500],
                "stdout_tail": (proc.stdout or "")[-500:],
            }))
            sys.exit(1)

        if not out_msh.exists():
            print(json.dumps({"ok": False, "error": "sphere.msh not produced"}))
            sys.exit(1)

        topo = parse_msh(out_msh)
        result = {
            "ok": True,
            "step": "sphere-mesh",
            "nodes": topo["nodes"],
            "elements": topo["elements"],
            "bbox": topo["bbox"],
            "solver": "gmsh",
        }
        print(json.dumps(result))


if __name__ == "__main__":
    main()
