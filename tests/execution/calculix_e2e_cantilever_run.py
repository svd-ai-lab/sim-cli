"""CalculiX E2E cantilever beam test.

Run via: sim run tests/execution/calculix_e2e_cantilever_run.py --solver calculix

Steps:
1. Write a minimal beam .inp deck (B32R beam elements)
2. Run ccx with LD_LIBRARY_PATH set
3. Parse .dat for tip (node 3) Y displacement
4. Emit JSON for sim to capture

Physics validation:
  Cantilever beam: L=10, RECT 0.1x0.1, E=200000, P=10 at tip in -Y
  Analytical tip deflection PL^3/(3EI):
    I = 0.1^4/12 = 8.33e-6
    delta = 10 * 1000 / (3 * 200000 * 8.33e-6) ~ 2000 (same units as deck)
  Acceptance: 500 < |tip_D2| < 5000 (wide band for coarse mesh + version tolerance)
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

INP_CONTENT = """*HEADING
Cantilever beam E2E - CalculiX
*NODE, NSET=NALL
1, 0.0, 0.0, 0.0
2, 5.0, 0.0, 0.0
3, 10.0, 0.0, 0.0
*ELEMENT, TYPE=B32R, ELSET=EALL
1, 1, 2, 3
*BOUNDARY
1, 1, 6
*MATERIAL, NAME=STEEL
*ELASTIC
200000.0, 0.3
*BEAM SECTION, ELSET=EALL, MATERIAL=STEEL, SECTION=RECT
0.1, 0.1
0.0, 0.0, 1.0
*STEP
*STATIC
*CLOAD
3, 2, -10.0
*NODE PRINT, NSET=NALL
U
*END STEP
"""


def find_ccx():
    candidates = [
        "/data/Chenyx/sim/opt/calculix/usr/bin/ccx",
        "/opt/calculix/bin/ccx",
        "/usr/bin/ccx",
    ]
    for c in candidates:
        if Path(c).is_file():
            return c
    import shutil
    return shutil.which("ccx")


def ld_path_for(ccx_bin):
    lib = Path(ccx_bin).parent.parent / "lib" / "x86_64-linux-gnu"
    return str(lib) if lib.is_dir() else None


def parse_dat_tip_disp(dat_path):
    """Parse .dat file for tip node (node 3) Y displacement from *NODE PRINT."""
    text = dat_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    # CalculiX .dat format (from *NODE PRINT U):
    #   displacements (vx,vy,vz) for set NALL and time  0.1000000E+01
    #
    #       1  6.617445E-24  4.160626E-18  0.000000E+00
    #       3 -1.342789E-06 -2.002205E+03  3.770545E-05
    #
    # We look for "displacements" header, then parse numeric rows.
    in_disp = False
    for line in lines:
        if "displacements" in line.lower() and "vx,vy,vz" in line.lower():
            in_disp = True
            continue
        if in_disp:
            parts = line.split()
            if len(parts) >= 4:
                try:
                    node = int(parts[0])
                    u1 = float(parts[1])
                    u2 = float(parts[2])
                    u3 = float(parts[3])
                    if node == 3:
                        return {"node": 3, "U1": u1, "U2": u2, "U3": u3}
                except ValueError:
                    # Header row or blank separator
                    if parts and not parts[0].replace('-', '').replace('.', '').replace('E', '').replace('e', '').replace('+', '').isdigit():
                        in_disp = False
    return None


def main():
    ccx = find_ccx()
    if ccx is None:
        print(json.dumps({"ok": False, "error": "ccx not found"}))
        sys.exit(1)

    with tempfile.TemporaryDirectory(prefix="sim_calculix_e2e_") as tmp:
        tmp = Path(tmp)
        inp = tmp / "beam.inp"
        inp.write_text(INP_CONTENT, encoding="utf-8")

        env = os.environ.copy()
        ld = ld_path_for(ccx)
        if ld:
            env["LD_LIBRARY_PATH"] = f"{ld}:{env.get('LD_LIBRARY_PATH', '')}"

        proc = subprocess.run(
            [ccx, "beam"],
            capture_output=True, text=True,
            cwd=str(tmp), env=env, timeout=120,
        )

        if proc.returncode != 0:
            print(json.dumps({
                "ok": False,
                "exit_code": proc.returncode,
                "stderr": (proc.stderr or "")[:500],
                "stdout_tail": (proc.stdout or "")[-500:],
            }))
            sys.exit(1)

        dat = tmp / "beam.dat"
        if not dat.exists():
            print(json.dumps({"ok": False, "error": "beam.dat not produced"}))
            sys.exit(1)

        tip = parse_dat_tip_disp(dat)
        if tip is None:
            print(json.dumps({
                "ok": False,
                "error": "could not parse tip displacement",
                "dat_head": dat.read_text()[:500],
            }))
            sys.exit(1)

        result = {
            "ok": True,
            "step": "cantilever-solve",
            "tip_node": tip["node"],
            "U1": tip["U1"],
            "U2": tip["U2"],
            "U3": tip["U3"],
            "tip_deflection_abs": abs(tip["U2"]),
            "solver": "calculix",
        }
        print(json.dumps(result))


if __name__ == "__main__":
    main()
