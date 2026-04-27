"""
PyFluent script support v0 demo: Solver - exhaust system.

Reads an existing case+data file and runs solver iterations.
Standalone pyfluent script - run via sim CLI:
    sim lint src/sim/drivers/pyfluent/examples/demo_solver_exhaust.py
    sim run  src/sim/drivers/pyfluent/examples/demo_solver_exhaust.py --solver=fluent --json
    sim query last --json
    sim log

Requirements:
  - Ansys Fluent 2024 R1 (AWP_ROOT241 set)
  - ansys-fluent-core 0.37.2
  - Local files: exhaust_system.cas.h5, exhaust_system.dat.h5

Reference:
  - src/sim/drivers/pyfluent/reference/pyfluent_examples/mixing_elbow_settings_api.md
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

# Patch _is_localhost so pyfluent accepts the machine's LAN IP for local launch.
import ansys.fluent.core.fluent_connection as _fc
_fc._is_localhost = lambda address: True

# -- Step 2: locate case/data files ------------------------------
step(2, "Locate exhaust_system.cas.h5 / .dat.h5 (local files)")

import os as _os
_datasets = _os.environ.get("SIM_DATASETS")
if not _datasets:
    print("  ERROR: SIM_DATASETS env var not set.")
    print("         Set it to the directory containing exhaust_system.cas.h5 / .dat.h5")
    sys.exit(1)
case_file = Path(_datasets) / "exhaust_system.cas.h5"
data_file = Path(_datasets) / "exhaust_system.dat.h5"

for f in [case_file, data_file]:
    if not f.exists():
        print(f"  ERROR: file not found: {f}")
        sys.exit(1)
    print(f"  found: {f.name}")

# -- Step 3: launch Fluent solver session (GUI) ------------------
step(3, "Launch Fluent solver session (GUI mode)")

print("  Calling pyfluent.launch_fluent(mode='solver', ui_mode='gui') ...")
try:
    solver = pyfluent.launch_fluent(
        mode="solver",
        ui_mode="gui",
        precision="double",
        processor_count=2,
    )
    print(f"  SUCCESS: session type = {type(solver).__name__}")
except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")
    sys.exit(1)

# -- Step 4: read case and data ----------------------------------
step(4, "Read case and data files")

try:
    solver.settings.file.read_case(file_name=str(case_file))
    print(f"  Case loaded: {case_file.name}")
    solver.settings.file.read_data(file_name=str(data_file))
    print(f"  Data loaded: {data_file.name}")
except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")
    solver.exit()
    sys.exit(1)

# -- Step 5: mesh check ------------------------------------------
step(5, "Mesh check")

try:
    solver.settings.mesh.check()
    print("  Mesh check OK")
except Exception as e:
    print(f"  WARNING: {type(e).__name__}: {e}")

# -- Step 6: run 20 iterations -----------------------------------
step(6, "Run 20 iterations")

try:
    solver.settings.solution.run_calculation.iterate(iter_count=20)
    print("  20 iterations complete")
except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")
    solver.exit()
    sys.exit(1)

# -- Step 7: compute mass flow rate ------------------------------
step(7, "Compute mass flow rate at outlet")

mass_flow = None
try:
    report_defs = solver.settings.solution.report_definitions
    report_defs.flux["mass_flow_rate"] = {}
    mfr = report_defs.flux["mass_flow_rate"]
    mfr.boundaries = ["outlet"]
    # compute() prints results to stdout; return value format varies by version
    report_defs.compute(report_defs=["mass_flow_rate"])
    mass_flow = "computed"
    print("  mass flow rate computed (see stdout above for value)")
except Exception as e:
    print(f"  WARNING: could not compute mass flow rate - {type(e).__name__}: {e}")

# -- Done --------------------------------------------------------
print(f"\n{'='*60}")
print("Solver demo complete - exhaust_system")
print("Visually confirm residuals in the Fluent GUI window")
print(f"{'='*60}")

print(json.dumps({
    "status": "ok",
    "workflow": "solver-exhaust-system",
    "case_file": str(case_file),
    "iterations_run": 20,
    "mass_flow_rate_outlet": mass_flow,
}))

try:
    #solver.exit()
    print('success')
except Exception:
    pass
