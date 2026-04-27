"""
PyFluent script support v0 demo: Fault-Tolerant Meshing workflow.

Standalone pyfluent script - run via sim CLI:
    sim lint src/sim/drivers/pyfluent/examples/demo_meshing_fault_tolerant.py
    sim run  src/sim/drivers/pyfluent/examples/demo_meshing_fault_tolerant.py --solver=fluent --json
    sim query last --json
    sim log

Requirements:
  - Ansys Fluent 2024 R1 (AWP_ROOT241 set)
  - ansys-fluent-core 0.37.2
  - exhaust_system.fmd at $SIM_DATASETS/exhaust_system.fmd
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

# Patch _is_localhost so pyfluent accepts the machine's LAN IP for local launch.
import ansys.fluent.core.fluent_connection as _fc
_fc._is_localhost = lambda address: True

# -- Step 2: locate geometry file --------------------------------
step(2, "Locate exhaust_system.fmd (local file)")

import os as _os
_datasets = _os.environ.get("SIM_DATASETS")
if not _datasets:
    print("  ERROR: SIM_DATASETS env var not set.")
    print("         Set it to the directory containing exhaust_system.fmd")
    sys.exit(1)
import_file_name = Path(_datasets) / "exhaust_system.fmd"
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

# -- Step 4: init Fault-Tolerant Meshing workflow ----------------
step(4, "InitializeWorkflow: Fault-tolerant Meshing")

try:
    workflow = meshing.workflow
    workflow.InitializeWorkflow(WorkflowType="Fault-tolerant Meshing")
    tasks = workflow.TaskObject
    print("  Workflow initialized OK")
except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")
    meshing.exit()
    sys.exit(1)

# -- Step 5: Part Management -------------------------------------
step(5, "Part Management: load exhaust_system.fmd")

try:
    part_management = meshing.PartManagement
    file_management = meshing.PMFileManagement
    part_management.InputFileChanged(
        FilePath=str(import_file_name),
        IgnoreSolidNames=False,
        PartPerBody=False,
    )
    file_management.FileManager.LoadFiles()
    part_management.Node["Meshing Model"].Copy(
        Paths=[
            "/dirty_manifold-for-wrapper,"
            "1/dirty_manifold-for-wrapper,1/main,1",
            "/dirty_manifold-for-wrapper,"
            "1/dirty_manifold-for-wrapper,1/flow-pipe,1",
            "/dirty_manifold-for-wrapper,"
            "1/dirty_manifold-for-wrapper,1/outpipe3,1",
            "/dirty_manifold-for-wrapper,"
            "1/dirty_manifold-for-wrapper,1/object2,1",
            "/dirty_manifold-for-wrapper,"
            "1/dirty_manifold-for-wrapper,1/object1,1",
        ]
    )
    part_management.ObjectSetting["DefaultObjectSetting"].OneZonePer.set_state("part")
    print("  Part Management OK")
except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")
    meshing.exit()
    sys.exit(1)

# -- Step 6: Import CAD and Part Management ----------------------
step(6, "Import CAD and Part Management")

try:
    import_cad = tasks["Import CAD and Part Management"]
    import_cad.Arguments.set_state({
        "Context": 0,
        "CreateObjectPer": "Custom",
        "FMDFileName": str(import_file_name),
        "FileLoaded": "yes",
        "ObjectSetting": "DefaultObjectSetting",
    })
    import_cad.Execute()
    print("  Import CAD OK")
except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")
    meshing.exit()
    sys.exit(1)

# -- Step 7: Describe Geometry and Flow --------------------------
step(7, "Describe Geometry and Flow")

try:
    describe_geometry = tasks["Describe Geometry and Flow"]
    describe_geometry.Arguments.set_state({
        "AddEnclosure": "No",
        "CloseCaps": "Yes",
        "FlowType": "Internal flow through the object",
    })
    describe_geometry.UpdateChildTasks(SetupTypeChanged=False)
    describe_geometry.Arguments.set_state({
        "AddEnclosure": "No",
        "CloseCaps": "Yes",
        "DescribeGeometryAndFlowOptions": {
            "AdvancedOptions": True,
            "ExtractEdgeFeatures": "Yes",
        },
        "FlowType": "Internal flow through the object",
    })
    describe_geometry.UpdateChildTasks(SetupTypeChanged=False)
    describe_geometry.Execute()
    print("  Describe Geometry and Flow OK")
except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")
    meshing.exit()
    sys.exit(1)

# -- Step 8: Enclose Fluid Regions (Capping) ---------------------
step(8, "Enclose Fluid Regions (Capping): inlet-1, inlet-2, inlet-3, outlet-1")

try:
    enclose = tasks["Enclose Fluid Regions (Capping)"]

    # inlet-1
    enclose.Arguments.set_state({
        "CreatePatchPreferences": {"ShowCreatePatchPreferences": False},
        "PatchName": "inlet-1",
        "SelectionType": "zone",
        "ZoneLocation": ["1", "351.68205", "-361.34322", "-301.88668",
                         "396.96205", "-332.84759", "-266.69751", "inlet.1"],
        "ZoneSelectionList": ["inlet.1"],
    })
    enclose.AddChildToTask()
    enclose.InsertCompoundChildTask()
    enclose.Arguments.set_state({})
    tasks["inlet-1"].Execute()

    # inlet-2
    enclose.Arguments.set_state({
        "PatchName": "inlet-2",
        "SelectionType": "zone",
        "ZoneLocation": ["1", "441.68205", "-361.34322", "-301.88668",
                         "486.96205", "-332.84759", "-266.69751", "inlet.2"],
        "ZoneSelectionList": ["inlet.2"],
    })
    enclose.AddChildToTask()
    enclose.InsertCompoundChildTask()
    enclose.Arguments.set_state({})
    tasks["inlet-2"].Execute()

    # inlet-3
    enclose.Arguments.set_state({
        "PatchName": "inlet-3",
        "SelectionType": "zone",
        "ZoneLocation": ["1", "261.68205", "-361.34322", "-301.88668",
                         "306.96205", "-332.84759", "-266.69751", "inlet"],
        "ZoneSelectionList": ["inlet"],
    })
    enclose.AddChildToTask()
    enclose.InsertCompoundChildTask()
    enclose.Arguments.set_state({})
    tasks["inlet-3"].Execute()

    # outlet-1
    enclose.Arguments.set_state({
        "PatchName": "outlet-1",
        "SelectionType": "zone",
        "ZoneLocation": ["1", "352.22702", "-197.8957", "84.102381",
                         "394.41707", "-155.70565", "84.102381", "outlet"],
        "ZoneSelectionList": ["outlet"],
        "ZoneType": "pressure-outlet",
    })
    enclose.AddChildToTask()
    enclose.InsertCompoundChildTask()
    enclose.Arguments.set_state({})
    tasks["outlet-1"].Execute()

    print("  Enclose Fluid Regions OK (4 patches)")
except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")
    meshing.exit()
    sys.exit(1)

# -- Step 9: Extract Edge Features -------------------------------
step(9, "Extract Edge Features")

try:
    extract_edge = tasks["Extract Edge Features"]
    extract_edge.Arguments.set_state({
        "ExtractMethodType": "Intersection Loops",
        "ObjectSelectionList": ["flow_pipe", "main"],
    })
    extract_edge.AddChildToTask()
    extract_edge.InsertCompoundChildTask()
    tasks["edge-group-1"].Arguments.set_state({
        "ExtractEdgesName": "edge-group-1",
        "ExtractMethodType": "Intersection Loops",
        "ObjectSelectionList": ["flow_pipe", "main"],
    })
    extract_edge.Arguments.set_state({})
    tasks["edge-group-1"].Execute()
    print("  Extract Edge Features OK")
except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")
    meshing.exit()
    sys.exit(1)

# -- Step 10: Identify Regions -----------------------------------
step(10, "Identify Regions: fluid-region-1, void-region-1")

try:
    identify = tasks["Identify Regions"]

    # fluid-region-1
    identify.Arguments.set_state({
        "SelectionType": "zone",
        "X": 377.322045740589,
        "Y": -176.800676988458,
        "Z": -37.0764628583475,
        "ZoneLocation": ["1", "213.32205", "-225.28068", "-158.25531",
                         "541.32205", "-128.32068", "84.102381", "main.1"],
        "ZoneSelectionList": ["main.1"],
    })
    identify.AddChildToTask()
    identify.InsertCompoundChildTask()
    tasks["fluid-region-1"].Arguments.set_state({
        "MaterialPointsName": "fluid-region-1",
        "SelectionType": "zone",
        "X": 377.322045740589,
        "Y": -176.800676988458,
        "Z": -37.0764628583475,
        "ZoneLocation": ["1", "213.32205", "-225.28068", "-158.25531",
                         "541.32205", "-128.32068", "84.102381", "main.1"],
        "ZoneSelectionList": ["main.1"],
    })
    identify.Arguments.set_state({})
    tasks["fluid-region-1"].Execute()

    # void-region-1
    identify.Arguments.set_state({
        "MaterialPointsName": "void-region-1",
        "NewRegionType": "void",
        "ObjectSelectionList": ["inlet-1", "inlet-2", "inlet-3", "main"],
        "X": 374.722045740589,
        "Y": -278.9775145640143,
        "Z": -161.1700719416913,
    })
    identify.AddChildToTask()
    identify.InsertCompoundChildTask()
    identify.Arguments.set_state({})
    tasks["void-region-1"].Execute()

    print("  Identify Regions OK")
except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")
    meshing.exit()
    sys.exit(1)

# -- Step 11: Define Leakage Threshold ---------------------------
step(11, "Define Leakage Threshold")

try:
    define_leakage = tasks["Define Leakage Threshold"]
    define_leakage.Arguments.set_state({
        "AddChild": "yes",
        "FlipDirection": True,
        "PlaneDirection": "X",
        "RegionSelectionSingle": "void-region-1",
    })
    define_leakage.AddChildToTask()
    define_leakage.InsertCompoundChildTask()
    tasks["leakage-1"].Arguments.set_state({
        "AddChild": "yes",
        "FlipDirection": True,
        "LeakageName": "leakage-1",
        "PlaneDirection": "X",
        "RegionSelectionSingle": "void-region-1",
    })
    define_leakage.Arguments.set_state({"AddChild": "yes"})
    tasks["leakage-1"].Execute()
    print("  Define Leakage Threshold OK")
except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")
    meshing.exit()
    sys.exit(1)

# -- Step 12: Update Region Settings -----------------------------
step(12, "Update Region Settings")

try:
    update_region = tasks["Update Region Settings"]
    update_region.Arguments.set_state({
        "AllRegionFilterCategories": ["2"] * 5 + ["1"] * 2,
        "AllRegionLeakageSizeList": ["none"] * 6 + ["6.4"],
        "AllRegionLinkedConstructionSurfaceList": ["n/a"] * 6 + ["no"],
        "AllRegionMeshMethodList": ["none"] * 6 + ["wrap"],
        "AllRegionNameList": [
            "main", "flow_pipe", "outpipe3", "object2",
            "object1", "void-region-1", "fluid-region-1",
        ],
        "AllRegionOversetComponenList": ["no"] * 7,
        "AllRegionSourceList": ["object"] * 5 + ["mpt"] * 2,
        "AllRegionTypeList": ["void"] * 6 + ["fluid"],
        "AllRegionVolumeFillList": ["none"] * 6 + ["tet"],
        "FilterCategory": "Identified Regions",
        "OldRegionLeakageSizeList": [""],
        "OldRegionMeshMethodList": ["wrap"],
        "OldRegionNameList": ["fluid-region-1"],
        "OldRegionOversetComponenList": ["no"],
        "OldRegionTypeList": ["fluid"],
        "OldRegionVolumeFillList": ["hexcore"],
        "RegionLeakageSizeList": [""],
        "RegionMeshMethodList": ["wrap"],
        "RegionNameList": ["fluid-region-1"],
        "RegionOversetComponenList": ["no"],
        "RegionTypeList": ["fluid"],
        "RegionVolumeFillList": ["tet"],
    })
    update_region.Execute()
    print("  Update Region Settings OK")
except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")
    meshing.exit()
    sys.exit(1)

# -- Step 13: Choose Mesh Control Options ------------------------
step(13, "Choose Mesh Control Options")

try:
    tasks["Choose Mesh Control Options"].Execute()
    print("  Choose Mesh Control Options OK")
except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")
    meshing.exit()
    sys.exit(1)

# -- Step 14: Generate Surface Mesh ------------------------------
step(14, "Generate the Surface Mesh")

try:
    tasks["Generate the Surface Mesh"].Execute()
    print("  Generate Surface Mesh OK")
except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")
    meshing.exit()
    sys.exit(1)

# -- Step 15: Update Boundaries ----------------------------------
step(15, "Update Boundaries")

try:
    tasks["Update Boundaries"].Execute()
    print("  Update Boundaries OK")
except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")
    meshing.exit()
    sys.exit(1)

# -- Step 16: Add Boundary Layers --------------------------------
step(16, "Add Boundary Layers (aspect-ratio_1)")

try:
    add_bl = tasks["Add Boundary Layers"]
    add_bl.AddChildToTask()
    add_bl.InsertCompoundChildTask()
    tasks["aspect-ratio_1"].Arguments.set_state({
        "BLControlName": "aspect-ratio_1",
    })
    add_bl.Arguments.set_state({})
    tasks["aspect-ratio_1"].Execute()
    print("  Add Boundary Layers OK")
except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")
    meshing.exit()
    sys.exit(1)

# -- Step 17: Generate Volume Mesh -------------------------------
step(17, "Generate the Volume Mesh")

try:
    create_volume_mesh = tasks["Generate the Volume Mesh"]
    create_volume_mesh.Arguments.set_state({
        "AllRegionNameList": [
            "main", "flow_pipe", "outpipe3", "object2",
            "object1", "void-region-1", "fluid-region-1",
        ],
        "AllRegionSizeList": ["11.33375"] * 7,
        "AllRegionVolumeFillList": ["none"] * 6 + ["tet"],
        "EnableParallel": True,
    })
    create_volume_mesh.Execute()
    print("  Generate Volume Mesh OK")
except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")
    meshing.exit()
    sys.exit(1)

# -- Step 18: Switch to Solver -----------------------------------
step(18, "Switch to Solver")

try:
    solver = meshing.switch_to_solver()
    print(f"  Switch OK, solver type = {type(solver).__name__}")
except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")
    meshing.exit()
    sys.exit(1)

# -- Done --------------------------------------------------------
print(f"\n{'='*60}")
print("All steps passed - Fault-Tolerant Meshing complete")
print("Visually confirm mesh in the Fluent GUI window")
print(f"{'='*60}")

print(json.dumps({
    "status": "ok",
    "workflow": "fault-tolerant-meshing",
    "geometry_file": str(import_file_name),
    "steps_completed": 18,
    "surface_mesh_done": True,
    "volume_mesh_done": True,
    "switch_to_solver_done": True,
}))

try:
    solver.exit()
except Exception:
    pass
