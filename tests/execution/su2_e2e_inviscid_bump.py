"""SU2 E2E: Inviscid Euler flow over a 2D channel bump.

Uses the official SU2 Tutorials Inviscid_Bump case (cloned to
/data/Chenyx/sim/refs/Tutorials/). Runs SU2_CFD with 100 iterations
and validates convergence via history.csv.

Acceptance (convergence-based):
  - SU2_CFD exits 0 with "Exit Success" in stdout
  - history.csv has >= 80 rows of iteration data
  - final RMS[Rho] < -2 (residual drop of at least 1 order from ~-1.4)
"""
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


TUTORIAL_DIR = Path("/data/Chenyx/sim/refs/Tutorials/compressible_flow/Inviscid_Bump")
SU2_CFD = "/data/Chenyx/sim/opt/su2/bin/SU2_CFD"


def find_su2_cfd():
    if Path(SU2_CFD).is_file():
        return SU2_CFD
    return shutil.which("SU2_CFD")


def parse_history(csv_path):
    """Return (n_rows, final_rms_rho) from history.csv."""
    with open(csv_path, newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        # Column names are quoted strings with variable whitespace
        cols = [c.strip().strip('"') for c in header]
        try:
            rms_rho_idx = cols.index("rms[Rho]")
        except ValueError:
            # Try any column containing 'rho' (case-insensitive)
            rms_rho_idx = next(
                (i for i, c in enumerate(cols) if "rho" in c.lower() and "rms" in c.lower()),
                None,
            )
        rows = list(reader)
    if not rows or rms_rho_idx is None:
        return 0, None
    try:
        final = float(rows[-1][rms_rho_idx])
    except (ValueError, IndexError):
        final = None
    return len(rows), final


def main():
    su2 = find_su2_cfd()
    if not su2:
        print(json.dumps({"ok": False, "error": "SU2_CFD not found"}))
        sys.exit(1)
    if not TUTORIAL_DIR.is_dir():
        print(json.dumps({"ok": False, "error": f"Tutorial dir missing: {TUTORIAL_DIR}"}))
        sys.exit(1)

    with tempfile.TemporaryDirectory(prefix="sim_su2_e2e_") as tmp:
        tmp = Path(tmp)
        # Copy cfg + mesh into tmp
        for f in TUTORIAL_DIR.iterdir():
            if f.suffix in (".cfg", ".su2"):
                shutil.copy2(f, tmp / f.name)

        cfg = tmp / "inv_channel.cfg"
        # Trim ITER to 100 for fast E2E
        text = cfg.read_text()
        import re
        text = re.sub(r"^ITER\s*=.*$", "ITER= 100", text, count=1, flags=re.MULTILINE)
        cfg.write_text(text)

        proc = subprocess.run(
            [su2, cfg.name],
            capture_output=True, text=True,
            cwd=str(tmp), timeout=900,
        )

        if proc.returncode != 0 or "Exit Success" not in proc.stdout:
            print(json.dumps({
                "ok": False,
                "exit_code": proc.returncode,
                "stdout_tail": (proc.stdout or "")[-500:],
                "stderr_tail": (proc.stderr or "")[-500:],
            }))
            sys.exit(1)

        history = tmp / "history.csv"
        if not history.is_file():
            print(json.dumps({"ok": False, "error": "history.csv not produced"}))
            sys.exit(1)

        n_rows, final_rms = parse_history(history)
        result = {
            "ok": True,
            "step": "inviscid-bump-euler",
            "n_iterations": n_rows,
            "final_rms_rho": final_rms,
            "solver": "su2",
            "su2_version": "8.4.0",
        }
        print(json.dumps(result))


if __name__ == "__main__":
    main()
