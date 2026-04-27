"""
PyFluent script support v0 demo: Watertight Geometry Meshing workflow.

This is a standalone pyfluent script intended to be run via sim CLI:
    sim lint src/sim/drivers/pyfluent/examples/demo_meshing_watertight.py
    sim run  src/sim/drivers/pyfluent/examples/demo_meshing_watertight.py --solver=fluent --json
    sim query last --json
    sim log

Requirements:
  - Ansys Fluent 2024 R1 (AWP_ROOT241 set)
  - ansys-fluent-core 0.37.2
  - GUI mode: visually confirm mesh in the Fluent window

Reference:
  - src/sim/drivers/pyfluent/reference/pyfluent_user_guide/meshing/meshing_workflows.md
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SEP = "-" * 60


def step(n: int, title: str) -> None:
    print(f"\n[Step {n}] {title}")
    print(SEP)


# -- Step 1: import ----------------------------------------------
step(1, "Import ansys-fluent-core")

try:
    import ansys.fluent.core as pyfluent
    print(f"  pyfluent version = {pyfluent.__version__}")
except ImportError as e:
    print(f"  ERROR: import failed - {e}")
    sys.exit(1)

# pyfluent 0.37.2 rejects non-loopback IPs as "remote hosts" even for local
# launches (Fluent advertises the machine's LAN IP in its server-info file).
# Patch _is_localhost to accept any address so the local connection proceeds.
import ansys.fluent.core.fluent_connection as _fc
_fc._is_localhost = lambda address: True

# -- Step 2: locate geometry file ---------------------------------
step(2, "Locate mixing_elbow.pmdb (local file)")

# Locate via SIM_DATASETS env var.
import os as _os
_datasets = _os.environ.get("SIM_DATASETS")
if not _datasets:
    print("  ERROR: SIM_DATASETS env var not set.")
    print("         Set it to the directory containing mixing_elbow.pmdb")
    sys.exit(1)
import_file_name = Path(_datasets) / "mixing_elbow.pmdb"
if not import_file_name.exists():
    print(f"  ERROR: file not found: {import_file_name}")
    sys.exit(1)
print(f"  path   = {import_file_name}")
print(f"  exists = True")

# -- Step 3: launch Fluent meshing session (GUI) ------------------
step(3, "Launch Fluent meshing session (GUI mode, ~30-60 s)")

print("  Calling pyfluent.launch_fluent(mode='meshing', ui_mode='gui') ...")
try:
    meshing = pyfluent.launch_fluent(
        mode="meshing",
        ui_mode="gui",
        precision="double",
        processor_count=2,
    )
    print(f"  SUCCESS: session type = {type(meshing).__name__}")
except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")
    sys.exit(1)

# -- Step 4: init Watertight Geometry workflow --------------------
step(4, "InitializeWorkflow: Watertight Geometry")

try:
    workflow = meshing.workflow
    workflow.InitializeWorkflow(WorkflowType="Watertight Geometry")
    tasks = workflow.TaskObject
    print("  Workflow initialized OK")
except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")
    meshing.exit()
    sys.exit(1)

# -- Step 5: Import Geometry --------------------------------------
step(5, "Import Geometry (unit: in)")

try:
    tasks["Import Geometry"].Arguments.set_state({
        "FileName": str(import_file_name),
        "LengthUnit": "in",
    })
    tasks["Import Geometry"].Execute()
    print("  Import Geometry OK")
except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")
    meshing.exit()
    sys.exit(1)

# -- Step 6: Add Local Sizing -------------------------------------
step(6, "Add Local Sizing")

try:
    tasks["Add Local Sizing"].AddChildToTask()
    tasks["Add Local Sizing"].Execute()
    print("  Add Local Sizing OK")
except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")
    meshing.exit()
    sys.exit(1)

# -- Step 7: Generate Surface Mesh -------------------------------
step(7, "Generate the Surface Mesh (MaxSize=0.3)")

try:
    tasks["Generate the Surface Mesh"].Arguments.set_state({
        "CFDSurfaceMeshControls": {"MaxSize": 0.3}
    })
    tasks["Generate the Surface Mesh"].Execute()
    print("  Generate Surface Mesh OK")
except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")
    meshing.exit()
    sys.exit(1)

# -- Step 8: Describe Geometry ------------------------------------
step(8, "Describe Geometry (fluid only)")

try:
    describe_geometry = tasks["Describe Geometry"]
    describe_geometry.UpdateChildTasks(SetupTypeChanged=False)
    describe_geometry.Arguments.set_state({
        "SetupType": "The geometry consists of only fluid regions with no voids"
    })
    describe_geometry.UpdateChildTasks(SetupTypeChanged=True)
    describe_geometry.Execute()
    print("  Describe Geometry OK")
except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")
    meshing.exit()
    sys.exit(1)

# -- Step 9: Update Boundaries ------------------------------------
step(9, "Update Boundaries")

try:
    tasks["Update Boundaries"].Execute()
    print("  Update Boundaries OK")
except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")
    meshing.exit()
    sys.exit(1)

# -- Step 10: Update Regions --------------------------------------
step(10, "Update Regions")

try:
    tasks["Update Regions"].Execute()
    print("  Update Regions OK")
except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")
    meshing.exit()
    sys.exit(1)

# -- Step 11: Add Boundary Layers ---------------------------------
step(11, "Add Boundary Layers (smooth-transition)")

try:
    tasks["Add Boundary Layers"].AddChildToTask()
    tasks["Add Boundary Layers"].InsertCompoundChildTask()
    tasks["smooth-transition_1"].Arguments.set_state({
        "BLControlName": "smooth-transition_1",
    })
    tasks["Add Boundary Layers"].Arguments.set_state({})
    tasks["smooth-transition_1"].Execute()
    print("  Add Boundary Layers OK")
except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")
    meshing.exit()
    sys.exit(1)

# -- Step 12: Generate Volume Mesh --------------------------------
step(12, "Generate the Volume Mesh (poly-hexcore)")

try:
    tasks["Generate the Volume Mesh"].Arguments.set_state({
        "VolumeFill": "poly-hexcore",
        "VolumeFillControls": {"HexMaxCellLength": 0.3},
    })
    tasks["Generate the Volume Mesh"].Execute()
    print("  Generate Volume Mesh OK")
except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")
    meshing.exit()
    sys.exit(1)

# -- Step 13: Switch to Solver ------------------------------------
step(13, "Switch to Solver")

try:
    solver = meshing.switch_to_solver()
    print(f"  Switch OK, solver type = {type(solver).__name__}")
except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")
    meshing.exit()
    sys.exit(1)

# -- Done ---------------------------------------------------------
print(f"\n{'='*60}")
print("All steps passed - Watertight Geometry Meshing complete")
print("Visually confirm mesh in the Fluent GUI window")
print(f"{'='*60}")

# Print structured JSON result for sim query last
print(json.dumps({
    "status": "ok",
    "workflow": "watertight-geometry",
    "geometry_file": str(import_file_name),
    "steps_completed": 13,
    "surface_mesh_done": True,
    "volume_mesh_done": True,
    "switch_to_solver_done": True,
}))

try:
    solver.exit()
except Exception:
    pass
