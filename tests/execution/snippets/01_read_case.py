# Step 1: Read mesh file.
#
# Looks for mixing_elbow.msh.h5 under $SIM_DATASETS.
# Set the env var before running:
#   PowerShell:  $env:SIM_DATASETS = "C:\path\to\datasets"
#   bash:        export SIM_DATASETS="/path/to/datasets"
import os
from pathlib import Path

datasets = os.environ.get("SIM_DATASETS")
if not datasets:
    raise RuntimeError(
        "SIM_DATASETS env var is not set. "
        "Set it to the directory containing mixing_elbow.msh.h5 before running."
    )

MESH_FILE = str(Path(datasets) / "mixing_elbow.msh.h5")
if not os.path.isfile(MESH_FILE):
    raise FileNotFoundError(f"Mesh file not found: {MESH_FILE}")

solver.settings.file.read_case(file_name=MESH_FILE)

_result = {"step": "read-case", "mesh_file": MESH_FILE, "ok": True}
