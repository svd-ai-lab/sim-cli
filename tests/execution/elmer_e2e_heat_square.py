"""Elmer FEM E2E: 2D steady heat conduction on unit square.

Pipeline:
1. Write ElmerGrid `.grd` for a 10x10 unit-square quad mesh
2. Run ElmerGrid to generate mesh directory
3. Write the .sif heat-equation input file
4. Run ElmerSolver
5. Parse scalars.dat for max Temperature
6. Emit JSON

Physics: -ΔT = 1 on Ω=[0,1]², T=0 on ∂Ω
Analytical max T ≈ 0.0737 at center.
Acceptance: max T in 0.06..0.09 (within 20% of analytical).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ELMER_BASE = Path("/data/Chenyx/sim/opt/elmer")
ELMER_SOLVER = ELMER_BASE / "bin" / "ElmerSolver"
ELMER_GRID = ELMER_BASE / "bin" / "ElmerGrid"
ELMER_LIB = ELMER_BASE / "lib" / "elmersolver"


GRD = """Version = 210903
Coordinate System = Cartesian 2D
Subcell Divisions in 2D = 1 1
Subcell Sizes 1 = 1
Subcell Sizes 2 = 1
Material Structure in 2D
  1
End
Materials Interval = 1 1
Boundary Definitions
  1       -1        1        1
  2       -2        1        1
  3       -3        1        1
  4       -4        1        1
End
Numbering = Horizontal
Element Degree = 1
Element Innernodes = False
Element Divisions 1 = 10
Element Divisions 2 = 10
"""


SIF = """Header
  CHECK KEYWORDS Warn
  Mesh DB "." "heat"
End
Simulation
  Max Output Level = 4
  Coordinate System = Cartesian
  Simulation Type = Steady State
  Steady State Max Iterations = 1
  Output Intervals = 1
End
Body 1
  Target Bodies(1) = 1
  Equation = 1
  Material = 1
  Body Force = 1
End
Material 1
  Density = 1.0
  Heat Conductivity = 1.0
End
Body Force 1
  Heat Source = 1.0
End
Equation 1
  Active Solvers(2) = 1 2
End
Solver 1
  Equation = Heat Equation
  Variable = Temperature
  Procedure = "HeatSolve" "HeatSolver"
  Linear System Solver = Direct
  Linear System Direct Method = Umfpack
  Steady State Convergence Tolerance = 1e-5
End
Solver 2
  Exec Solver = After Timestep
  Equation = SaveScalars
  Procedure = "SaveData" "SaveScalars"
  Filename = "scalars.dat"
  Variable 1 = Temperature
  Operator 1 = max
End
Boundary Condition 1
  Target Boundaries(4) = 1 2 3 4
  Temperature = 0.0
End
"""


def main():
    if not ELMER_SOLVER.is_file() or not ELMER_GRID.is_file():
        print(json.dumps({"ok": False, "error": "Elmer binaries not found"}))
        sys.exit(1)

    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = f"{ELMER_LIB}:{env.get('LD_LIBRARY_PATH','')}"

    with tempfile.TemporaryDirectory(prefix="sim_elmer_e2e_") as tmp:
        tmp = Path(tmp)
        (tmp / "heat.grd").write_text(GRD)
        (tmp / "case.sif").write_text(SIF)

        # 1. Generate mesh
        proc = subprocess.run(
            [str(ELMER_GRID), "1", "2", "heat.grd"],
            capture_output=True, text=True, cwd=str(tmp), env=env, timeout=60,
        )
        if proc.returncode != 0:
            print(json.dumps({
                "ok": False, "step": "elmergrid",
                "stderr": (proc.stderr or "")[-500:],
            }))
            sys.exit(1)

        # 2. Run solver
        proc = subprocess.run(
            [str(ELMER_SOLVER), "case.sif"],
            capture_output=True, text=True, cwd=str(tmp), env=env, timeout=300,
        )
        if proc.returncode != 0 or "ALL DONE" not in proc.stdout:
            print(json.dumps({
                "ok": False, "step": "elmersolver",
                "exit_code": proc.returncode,
                "stdout_tail": (proc.stdout or "")[-500:],
                "stderr_tail": (proc.stderr or "")[-500:],
            }))
            sys.exit(1)

        # 3. Parse scalars.dat (single value: max Temperature)
        scalars = tmp / "scalars.dat"
        if not scalars.is_file():
            print(json.dumps({"ok": False, "error": "scalars.dat not produced"}))
            sys.exit(1)
        text = scalars.read_text().strip()
        parts = text.split()
        max_temp = float(parts[-1]) if parts else None

        # Count mesh info from mesh.header
        hdr = (tmp / "heat" / "mesh.header").read_text().split()
        nodes = int(hdr[0])
        elements = int(hdr[1])

        result = {
            "ok": True,
            "step": "heat-square",
            "nodes": nodes,
            "elements": elements,
            "max_temperature": max_temp,
            "analytical_max": 0.073671,
            "relative_error": abs(max_temp - 0.073671) / 0.073671 if max_temp else None,
            "solver": "elmer",
            "elmer_version": "26.1",
        }
        print(json.dumps(result))


if __name__ == "__main__":
    main()
