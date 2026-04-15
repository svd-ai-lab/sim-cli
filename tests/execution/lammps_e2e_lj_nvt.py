"""LAMMPS E2E: Lennard-Jones liquid equilibration under NVT ensemble.

Run via: sim run tests/execution/lammps_e2e_lj_nvt.py --solver lammps

Steps:
1. Write minimal LJ + NVT input script
2. Run `lmp -in` via subprocess
3. Parse log.lammps for final thermo (temp, pressure, energy)
4. Emit JSON

Acceptance (physics):
  Target temp 1.5 (LJ units), NVT thermostat with tau=0.1
  - Simulation completes 50 steps with exit 0
  - final_temp within 0.5..2.5 (Nose-Hoover should equilibrate toward target)
  - total energy is finite (not NaN)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


LMP_CANDIDATES = [
    "/data/Chenyx/sim/opt/lammps/src/lmp_serial",
    "/data/Chenyx/sim/opt/lammps/bin/lmp",
    "/data/Chenyx/sim/sim-cli/.venv/bin/lmp",
]


INPUT = """# LJ liquid NVT equilibration (LAMMPS E2E)
units           lj
atom_style      atomic
dimension       3
boundary        p p p

lattice         fcc 0.8442
region          box block 0 5 0 5 0 5
create_box      1 box
create_atoms    1 box
mass            1 1.0

velocity        all create 1.5 12345 mom yes rot yes

pair_style      lj/cut 2.5
pair_coeff      1 1 1.0 1.0 2.5

neighbor        0.3 bin
neigh_modify    every 20 delay 0 check no

fix             1 all nvt temp 1.5 1.5 0.1

thermo          10
thermo_style    custom step temp press pe etotal

run             50
"""


def find_lmp():
    for c in LMP_CANDIDATES:
        if Path(c).is_file() and os.access(c, os.X_OK):
            return c
    return shutil.which("lmp") or shutil.which("lmp_serial") or shutil.which("lmp_mpi")


def parse_log(log_path):
    """Parse final thermo row from log.lammps.

    LAMMPS prints a thermo block like:
       Step Temp Press PotEng TotEng
         0  1.5    ...
        10  1.47   ...
        50  1.48   ...
    The row immediately after "Step" header line is first data row;
    we take the last numeric row before "Loop time" footer.
    """
    text = log_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    in_block = False
    header = None
    last_row = None
    for line in lines:
        # Header like "Step Temp Press PotEng TotEng"
        if re.match(r"^\s*Step\s+\w", line):
            header = line.split()
            in_block = True
            continue
        if in_block:
            if line.startswith("Loop time") or not line.strip():
                in_block = False
                continue
            parts = line.split()
            # Numeric row: first token is an integer step
            if parts and parts[0].isdigit() and len(parts) == len(header):
                last_row = parts
    if header and last_row:
        return dict(zip(header, last_row))
    return None


def main():
    lmp = find_lmp()
    if not lmp:
        print(json.dumps({"ok": False, "error": "lmp binary not found"}))
        sys.exit(1)

    with tempfile.TemporaryDirectory(prefix="sim_lammps_e2e_") as tmp:
        tmp = Path(tmp)
        inp = tmp / "lj.in"
        inp.write_text(INPUT, encoding="utf-8")

        proc = subprocess.run(
            [lmp, "-in", inp.name],
            capture_output=True, text=True,
            cwd=str(tmp), timeout=120,
        )
        if proc.returncode != 0:
            print(json.dumps({
                "ok": False,
                "exit_code": proc.returncode,
                "stderr_tail": (proc.stderr or "")[-500:],
                "stdout_tail": (proc.stdout or "")[-500:],
            }))
            sys.exit(1)

        log = tmp / "log.lammps"
        if not log.is_file():
            print(json.dumps({"ok": False, "error": "log.lammps not produced"}))
            sys.exit(1)

        thermo = parse_log(log)
        if thermo is None:
            print(json.dumps({
                "ok": False,
                "error": "could not parse thermo from log.lammps",
                "log_tail": log.read_text()[-500:],
            }))
            sys.exit(1)

        result = {
            "ok": True,
            "step": "lj-nvt",
            "final_step": int(thermo.get("Step", 0)),
            "final_temp": float(thermo.get("Temp", 0)),
            "final_press": float(thermo.get("Press", 0)),
            "final_pe": float(thermo.get("PotEng", 0)),
            "final_etotal": float(thermo.get("TotEng", 0)),
            "solver": "lammps",
        }
        print(json.dumps(result))


if __name__ == "__main__":
    main()
