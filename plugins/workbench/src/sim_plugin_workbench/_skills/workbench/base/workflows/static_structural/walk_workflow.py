"""Static Structural 6-Step Workflow Walk.

Walks all 6 cells of a Static Structural system and reports what's
reachable at the Workbench orchestration layer — without invoking
Mechanical for the actual solve.

Run as IronPython journal via sim exec (sends this entire file to
run_script_string).

Result file: %TEMP%/sim_wb_result.json with:
  - walk: list of 6 step results
  - all_ok: True if all steps reached
"""
import json, os, codecs

# Create fresh Static Structural system
SetScriptVersion(Version="24.1")
t = GetTemplate(TemplateName="Static Structural", Solver="ANSYS")
s = t.CreateSystem()

walk = []

# ========================================================================
# Step 1: Engineering Data
# ========================================================================
eng = s.GetContainer(ComponentName="Engineering Data")
materials = eng.GetMaterials()
walk.append({
    "step": 1,
    "cell": "Engineering Data",
    "ok": len(materials) > 0,
    "material_count": len(materials),
    "default_material": "Structural Steel",
})

# ========================================================================
# Step 2: Geometry
# ========================================================================
geo = s.GetContainer(ComponentName="Geometry")
props = geo.GetGeometryProperties()
walk.append({
    "step": 2,
    "cell": "Geometry",
    "ok": props is not None,
    "api": {
        "SetFile": hasattr(geo, "SetFile"),
        "Edit": hasattr(geo, "Edit"),
        "Refresh": hasattr(geo, "Refresh"),
        "UpdateCAD": hasattr(geo, "UpdateCAD"),
    },
    "note": "SetFile requires ABSOLUTE path (CWD != TEMP)",
})

# ========================================================================
# Step 3: Model — canonical physics query point
# ========================================================================
model = s.GetContainer(ComponentName="Model")
phys_class = str(model.GetMechanicalSystemType())
walk.append({
    "step": 3,
    "cell": "Model",
    "ok": "Static" in phys_class and "ANSYS" in phys_class,
    "physics": phys_class,
    "api": {
        "GetMechanicalSystemType": True,
        "GetMechanicalMesh": hasattr(model, "GetMechanicalMesh"),
        "ExportMesh": hasattr(model, "ExportMesh"),
        "ExportGeometry": hasattr(model, "ExportGeometry"),
    },
    "note": "Canonical physics query lives here, not in Setup",
})

# ========================================================================
# Step 4: Setup — GetPhysicsType() is a trap
# ========================================================================
setup = s.GetContainer(ComponentName="Setup")
phys_type_failed = False
phys_err = ""
try:
    _ = str(setup.GetPhysicsType())
except Exception as e:
    phys_type_failed = True
    phys_err = str(e)[:80]

walk.append({
    "step": 4,
    "cell": "Setup",
    "ok": hasattr(setup, "Edit"),
    "gotcha_physics_type_fails": phys_type_failed,
    "gotcha_error_excerpt": phys_err,
    "api": {
        "Edit": hasattr(setup, "Edit"),
        "GetMechanicalSetupFile": hasattr(setup, "GetMechanicalSetupFile"),
        "SendCommand": hasattr(setup, "SendCommand"),
    },
    "note": "GetPhysicsType() fails before solve. Use Model.GetMechanicalSystemType().",
})

# ========================================================================
# Step 5: Solution
# ========================================================================
sol = s.GetContainer(ComponentName="Solution")
expert_ok = False
try:
    _ = sol.GetExpertProperties()
    expert_ok = True
except Exception:
    pass

walk.append({
    "step": 5,
    "cell": "Solution",
    "ok": expert_ok,
    "expert_properties_accessible": expert_ok,
    "api": {
        "GetSolutionSettings": hasattr(sol, "GetSolutionSettings"),
        "GetExpertProperties": hasattr(sol, "GetExpertProperties"),
        "Edit": hasattr(sol, "Edit"),
    },
    "note": "GetExpertProperties works; GetPhysicsType still fails (same trap).",
})

# ========================================================================
# Step 6: Results
# ========================================================================
res = s.GetContainer(ComponentName="Results")
walk.append({
    "step": 6,
    "cell": "Results",
    "ok": hasattr(res, "GetSimulationResultFile"),
    "api": {
        "GetSimulationResultFile": hasattr(res, "GetSimulationResultFile"),
        "Edit": hasattr(res, "Edit"),
        "EditPost": hasattr(res, "EditPost"),
    },
    "note": "Result file access for post-processing handoff.",
})

# ========================================================================
# Write result
# ========================================================================
all_ok = all(item["ok"] for item in walk)
result = {
    "ok": all_ok,
    "step": "static-structural-workflow-walk",
    "all_cells_reachable": all_ok,
    "walk": walk,
}

out = os.path.join(os.environ.get("TEMP", "C:/Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps(result))
f.close()
