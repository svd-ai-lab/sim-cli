"""Abaqus E2E cantilever beam test — wraps .inp execution + .dat parsing.

Run via: sim run tests/execution/abaqus_e2e_cantilever_run.py --solver abaqus

This script:
1. Writes a minimal cantilever beam input deck
2. Runs Abaqus on it via subprocess
3. Parses the .dat file for tip displacement
4. Emits JSON result for sim to capture

Physics validation:
  Beam: L=10m, b=1m, h=1m, E=200GPa, P=1000N tip load
  Analytical tip deflection PL^3/(3EI) ~ 2e-5 m
  FEM with coarse mesh: expect 1e-6 to 1e-4 m range
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

INP_CONTENT = r"""*HEADING
Cantilever beam under tip load - sim E2E verification
**
*NODE
      1,  0.0,  0.0,  0.0
      2,  2.5,  0.0,  0.0
      3,  5.0,  0.0,  0.0
      4,  7.5,  0.0,  0.0
      5, 10.0,  0.0,  0.0
      6, 10.0,  1.0,  0.0
      7,  7.5,  1.0,  0.0
      8,  5.0,  1.0,  0.0
      9,  2.5,  1.0,  0.0
     10,  0.0,  1.0,  0.0
**
*ELEMENT, TYPE=CPS4, ELSET=BEAM
1,  1,  2,  9, 10
2,  2,  3,  8,  9
3,  3,  4,  7,  8
4,  4,  5,  6,  7
**
*MATERIAL, NAME=STEEL
*ELASTIC
200.0E9, 0.3
**
*SOLID SECTION, ELSET=BEAM, MATERIAL=STEEL
1.0,
**
*NSET, NSET=FIXED
1, 10
*NSET, NSET=TIP
5
**
*STEP, NAME=STATIC_LOAD
*STATIC
**
*BOUNDARY
FIXED, 1, 2
**
*CLOAD
TIP, 2, -1000.0
**
*NODE PRINT, NSET=TIP
U,
**
*END STEP
"""


def find_abaqus_cmd():
    """Find the abaqus command."""
    for drive in ("E", "C", "D"):
        bat = Path(f"{drive}:/Program Files (x86)/Dassault Systemes/SIMULIA/Commands/abaqus.bat")
        if bat.is_file():
            return str(bat)
    # Fallback to PATH
    import shutil
    return shutil.which("abaqus") or "abaqus"


def parse_dat_for_tip_displacement(dat_path: Path) -> dict:
    """Parse .dat file to extract tip node displacement."""
    text = dat_path.read_text(encoding="utf-8", errors="replace")

    # Look for the displacement table for TIP node set
    m = re.search(
        r"NODE SET TIP.*?(\d+)\s+([-\dE.+]+)\s+([-\dE.+]+)",
        text,
        re.DOTALL,
    )
    if not m:
        return {"ok": False, "error": "Could not parse tip displacement from .dat"}

    node = int(m.group(1))
    u1 = float(m.group(2))
    u2 = float(m.group(3))

    return {
        "ok": True,
        "node": node,
        "U1_m": u1,
        "U2_m": u2,
        "tip_deflection_m": abs(u2),
    }


def main():
    abaqus_cmd = find_abaqus_cmd()

    # Use a temp dir for the run
    with tempfile.TemporaryDirectory(prefix="sim_abaqus_e2e_") as tmpdir:
        inp_file = Path(tmpdir) / "cantilever.inp"
        inp_file.write_text(INP_CONTENT, encoding="utf-8")

        # Run Abaqus
        proc = subprocess.run(
            [abaqus_cmd, "job=cantilever", "input=cantilever.inp", "interactive"],
            capture_output=True,
            text=True,
            cwd=tmpdir,
            timeout=120,
        )

        if proc.returncode != 0:
            result = {
                "ok": False,
                "exit_code": proc.returncode,
                "stderr": proc.stderr[:500] if proc.stderr else "",
                "stdout": proc.stdout[:500] if proc.stdout else "",
            }
            print(json.dumps(result))
            sys.exit(1)

        # Parse results from .dat
        dat_file = Path(tmpdir) / "cantilever.dat"
        if not dat_file.exists():
            print(json.dumps({"ok": False, "error": ".dat file not created"}))
            sys.exit(1)

        result = parse_dat_for_tip_displacement(dat_file)
        result["solver_output"] = "Abaqus completed successfully"
        print(json.dumps(result))


if __name__ == "__main__":
    main()
