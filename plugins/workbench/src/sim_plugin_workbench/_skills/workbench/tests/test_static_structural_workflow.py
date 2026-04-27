"""Static Structural 6-step workflow tests.

The canonical Workbench Static Structural workflow consists of 6 cells:
    Engineering Data → Geometry → Model → Setup → Solution → Results

Each test validates one step using ONLY Workbench-level orchestration APIs
(not PyMechanical/PyFluent, which are separate skills). We test:

  1. What WORKS at each step without a geometry file
  2. What FAILS and why (gotchas to document in skill)
  3. The correct call sequence for each step

Findings from exploration:
- Engineering Data has "Structural Steel" by default
- Geometry.GetGeometryProperties() works even without file attached
- Model.GetMechanicalSystemType() works, exposes physics class
- Setup/Solution/Results.GetPhysicsType() FAILS before solve — use Model instead
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

try:
    import ansys.workbench.core as pywb
    HAS_SDK = True
except ImportError:
    HAS_SDK = False

try:
    from sim_plugin_workbench import WorkbenchDriver
    _d = WorkbenchDriver()
    HAS_WORKBENCH = len(_d.detect_installed()) > 0
except Exception:
    HAS_WORKBENCH = False

skip_no_env = pytest.mark.skipif(
    not (HAS_SDK and HAS_WORKBENCH),
    reason="PyWorkbench SDK or Ansys Workbench not available",
)

TEMP = os.environ.get("TEMP", "C:/Temp")
RESULT_FILE = Path(TEMP) / "sim_wb_result.json"


@pytest.fixture(scope="module")
def wb():
    """Single Workbench session for all workflow tests."""
    client = pywb.launch_workbench(release="241")
    time.sleep(5)
    yield client


def _run(wb, code: str, wait: float = 2) -> dict:
    if RESULT_FILE.exists():
        RESULT_FILE.unlink()
    wb.run_script_string(code, log_level="warning")
    time.sleep(wait)
    if RESULT_FILE.exists():
        return json.loads(RESULT_FILE.read_text(encoding="utf-8"))
    return {}


@pytest.fixture(scope="module")
def static_system(wb):
    """Create one Static Structural system shared across all workflow tests."""
    _run(wb, '''
import json, os, codecs
t = GetTemplate(TemplateName="Static Structural", Solver="ANSYS")
s = t.CreateSystem()
out = os.path.join(os.environ.get("TEMP", "C:/Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": True, "step": "system-created"}))
f.close()
''')
    return "SYS"  # Newly created systems get name "SYS" by default


# ===========================================================================
# Step 1: Engineering Data
# ===========================================================================

@skip_no_env
class TestStep1_EngineeringData:
    """Engineering Data: material library management."""

    def test_default_material_structural_steel(self, wb, static_system):
        """A fresh Static Structural system ships with Structural Steel."""
        r = _run(wb, '''
import json, os, codecs
s = GetAllSystems()[0]
eng = s.GetContainer(ComponentName="Engineering Data")
mats = eng.GetMaterials()
count = len(mats) if mats else 0
names = [str(m.Name) for m in mats] if mats else []
out = os.path.join(os.environ.get("TEMP", "C:/Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": count >= 1, "count": count, "names": names}))
f.close()
''')
        assert r.get("ok") is True, f"Engineering Data empty: {r}"
        assert "Structural Steel" in r.get("names", [])

    def test_create_custom_material(self, wb):
        """Can create a new material entry programmatically."""
        r = _run(wb, '''
import json, os, codecs
s = GetAllSystems()[0]
eng = s.GetContainer(ComponentName="Engineering Data")
# Create a new material (will use default values)
try:
    mat = eng.CreateMaterial(Name="Test_Aluminum")
    ok = True
    name = str(mat.Name) if mat else ""
except Exception as e:
    ok = False
    name = ""
mats_after = eng.GetMaterials()
count = len(mats_after) if mats_after else 0
out = os.path.join(os.environ.get("TEMP", "C:/Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": ok and count >= 2, "created": name, "total": count}))
f.close()
''')
        assert r.get("ok") is True, f"CreateMaterial failed: {r}"
        assert r.get("created") == "Test_Aluminum"


# ===========================================================================
# Step 2: Geometry
# ===========================================================================

@skip_no_env
class TestStep2_Geometry:
    """Geometry cell: file attachment and properties."""

    def test_geometry_properties_accessible(self, wb, static_system):
        """GetGeometryProperties works even without a file attached."""
        r = _run(wb, '''
import json, os, codecs
s = GetAllSystems()[0]
geo = s.GetContainer(ComponentName="Geometry")
props = geo.GetGeometryProperties()
has_props = props is not None
out = os.path.join(os.environ.get("TEMP", "C:/Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": has_props, "has_properties": has_props}))
f.close()
''')
        assert r.get("ok") is True

    def test_set_file_with_absolute_path(self, wb):
        """SetFile accepts absolute path (relative path fails: CWD is not TEMP)."""
        dummy = Path(TEMP) / "sim_wf_dummy.agdb"
        dummy.write_bytes(b"DUMMY")
        import ansys.workbench.core as pywb_local

        # Use existing wb session from fixture — create system for this test
        r = _run(wb, '''
import json, os, codecs
t = GetTemplate(TemplateName="Static Structural", Solver="ANSYS")
s = t.CreateSystem()
geo = s.GetContainer(ComponentName="Geometry")
# Relative path — FAILS because Workbench CWD != TEMP
rel_err = ""
try:
    geo.SetFile(FilePath="sim_wf_dummy.agdb")
    rel_ok = True
except Exception as e:
    rel_ok = False
    rel_err = str(e)[:100]
# Absolute path — WORKS
abs_path = os.path.join(os.environ.get("TEMP", "C:/Temp"), "sim_wf_dummy.agdb")
abs_err = ""
try:
    geo.SetFile(FilePath=abs_path)
    abs_ok = True
except Exception as e:
    abs_ok = False
    abs_err = str(e)[:100]
out = os.path.join(os.environ.get("TEMP", "C:/Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({
    "ok": abs_ok,
    "abs_path_ok": abs_ok,
    "abs_err": abs_err,
}))
f.close()
''')
        # upload the dummy first
        import ansys.workbench.core
        wb.upload_file(str(dummy))
        # re-run
        r = _run(wb, '''
import json, os, codecs
# Create a NEW system for this test
t = GetTemplate(TemplateName="Static Structural", Solver="ANSYS")
s = t.CreateSystem()
geo = s.GetContainer(ComponentName="Geometry")
abs_path = os.path.join(os.environ.get("TEMP", "C:/Temp"), "sim_wf_dummy.agdb")
err = ""
try:
    geo.SetFile(FilePath=abs_path)
    ok = True
except Exception as e:
    ok = False
    err = str(e)[:100]
out = os.path.join(os.environ.get("TEMP", "C:/Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": ok, "error": err}))
f.close()
''')
        dummy.unlink()
        assert r.get("ok") is True, f"Absolute SetFile failed: {r}"


# ===========================================================================
# Step 3: Model
# ===========================================================================

@skip_no_env
class TestStep3_Model:
    """Model cell: mesh access and physics type."""

    def test_model_physics_type(self, wb, static_system):
        """Model.GetMechanicalSystemType() reveals the physics domain.

        This is the CORRECT way to query system physics — NOT via
        Setup/Solution/Results which fail before solve.
        """
        r = _run(wb, '''
import json, os, codecs
s = GetAllSystems()[0]
model = s.GetContainer(ComponentName="Model")
phys = str(model.GetMechanicalSystemType())
out = os.path.join(os.environ.get("TEMP", "C:/Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": "Static" in phys, "physics": phys}))
f.close()
''')
        assert r.get("ok") is True, f"Model physics query failed: {r}"
        assert "Static" in r.get("physics", "")
        assert "ANSYS" in r.get("physics", "")

    def test_model_has_mesh_api(self, wb, static_system):
        """Model container exposes mesh export methods."""
        r = _run(wb, '''
import json, os, codecs
s = GetAllSystems()[0]
model = s.GetContainer(ComponentName="Model")
has_methods = {
    "ExportMesh": hasattr(model, "ExportMesh"),
    "GetMechanicalMesh": hasattr(model, "GetMechanicalMesh"),
    "GetMeshProperties": hasattr(model, "GetMeshProperties"),
    "ExportGeometry": hasattr(model, "ExportGeometry"),
}
all_present = all(has_methods.values())
out = os.path.join(os.environ.get("TEMP", "C:/Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": all_present, "methods": has_methods}))
f.close()
''')
        assert r.get("ok") is True


# ===========================================================================
# Step 4: Setup (GOTCHA zone)
# ===========================================================================

@skip_no_env
class TestStep4_Setup:
    """Setup cell: boundary conditions and analysis settings.

    GOTCHA: GetPhysicsType() fails before the solve has run. Must query
    from Model.GetMechanicalSystemType() instead.
    """

    def test_setup_physicstype_fails_before_solve(self, wb, static_system):
        """Document the gotcha: GetPhysicsType raises before solve."""
        r = _run(wb, '''
import json, os, codecs
s = GetAllSystems()[0]
setup = s.GetContainer(ComponentName="Setup")
# This SHOULD fail with "Setup不包含所需的实体类型PhysicsType"
raised = False
err_msg = ""
try:
    pt = str(setup.GetPhysicsType())
except Exception as e:
    raised = True
    err_msg = str(e)[:100]
out = os.path.join(os.environ.get("TEMP", "C:/Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({
    "ok": raised,
    "raised_as_expected": raised,
    "error_excerpt": err_msg[:80],
}))
f.close()
''')
        assert r.get("ok") is True, (
            "Expected GetPhysicsType to raise before solve, but it succeeded"
        )

    def test_setup_has_edit_method(self, wb, static_system):
        """Setup exposes Edit() to open the setup editor."""
        r = _run(wb, '''
import json, os, codecs
s = GetAllSystems()[0]
setup = s.GetContainer(ComponentName="Setup")
methods = {
    "Edit": hasattr(setup, "Edit"),
    "Exit": hasattr(setup, "Exit"),
    "SendCommand": hasattr(setup, "SendCommand"),
    "GetMechanicalSetupFile": hasattr(setup, "GetMechanicalSetupFile"),
}
out = os.path.join(os.environ.get("TEMP", "C:/Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": all(methods.values()), "methods": methods}))
f.close()
''')
        assert r.get("ok") is True


# ===========================================================================
# Step 5: Solution (GOTCHA zone)
# ===========================================================================

@skip_no_env
class TestStep5_Solution:
    """Solution cell: solver settings and execution."""

    def test_solution_expert_properties(self, wb, static_system):
        """GetExpertProperties works (unlike GetPhysicsType)."""
        r = _run(wb, '''
import json, os, codecs
s = GetAllSystems()[0]
sol = s.GetContainer(ComponentName="Solution")
props = None
err = ""
try:
    props = sol.GetExpertProperties()
    ok = True
except Exception as e:
    ok = False
    err = str(e)[:100]
out = os.path.join(os.environ.get("TEMP", "C:/Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": ok, "error": err}))
f.close()
''')
        assert r.get("ok") is True

    def test_solution_has_solver_methods(self, wb, static_system):
        """Solution container exposes solver control methods."""
        r = _run(wb, '''
import json, os, codecs
s = GetAllSystems()[0]
sol = s.GetContainer(ComponentName="Solution")
methods = {
    "Edit": hasattr(sol, "Edit"),
    "GetSolutionSettings": hasattr(sol, "GetSolutionSettings"),
    "GetExpertProperties": hasattr(sol, "GetExpertProperties"),
    "SendCommand": hasattr(sol, "SendCommand"),
}
out = os.path.join(os.environ.get("TEMP", "C:/Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": all(methods.values()), "methods": methods}))
f.close()
''')
        assert r.get("ok") is True


# ===========================================================================
# Step 6: Results
# ===========================================================================

@skip_no_env
class TestStep6_Results:
    """Results cell: post-processing and result file access."""

    def test_results_has_simulation_file_api(self, wb, static_system):
        """Results exposes GetSimulationResultFile for post-processing."""
        r = _run(wb, '''
import json, os, codecs
s = GetAllSystems()[0]
res = s.GetContainer(ComponentName="Results")
methods = {
    "Edit": hasattr(res, "Edit"),
    "EditPost": hasattr(res, "EditPost"),
    "GetSimulationResultFile": hasattr(res, "GetSimulationResultFile"),
    "GetSimulationImportOptionsForResult": hasattr(res, "GetSimulationImportOptionsForResult"),
}
out = os.path.join(os.environ.get("TEMP", "C:/Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": all(methods.values()), "methods": methods}))
f.close()
''')
        assert r.get("ok") is True


# ===========================================================================
# Step 7: Full workflow walk — all 6 steps in one test
# ===========================================================================

@skip_no_env
class TestFullWorkflowWalk:
    """Walk all 6 steps in sequence, validate each is reachable."""

    def test_walk_all_six_steps(self, wb):
        """Traverse the entire Static Structural workflow tree."""
        r = _run(wb, '''
import json, os, codecs

# Create fresh system
t = GetTemplate(TemplateName="Static Structural", Solver="ANSYS")
s = t.CreateSystem()

walk = []

# 1. Engineering Data
eng = s.GetContainer(ComponentName="Engineering Data")
mats = eng.GetMaterials()
walk.append({"step": "Engineering Data", "ok": len(mats) > 0, "materials": len(mats)})

# 2. Geometry
geo = s.GetContainer(ComponentName="Geometry")
walk.append({"step": "Geometry", "ok": geo is not None, "has_api": hasattr(geo, "SetFile")})

# 3. Model
model = s.GetContainer(ComponentName="Model")
phys = str(model.GetMechanicalSystemType())
walk.append({"step": "Model", "ok": "Static" in phys, "physics": phys[:60]})

# 4. Setup (use Edit/Exit API, not GetPhysicsType)
setup = s.GetContainer(ComponentName="Setup")
walk.append({"step": "Setup", "ok": hasattr(setup, "Edit"), "has_edit": hasattr(setup, "Edit")})

# 5. Solution
sol = s.GetContainer(ComponentName="Solution")
walk.append({"step": "Solution", "ok": hasattr(sol, "GetSolutionSettings")})

# 6. Results
res = s.GetContainer(ComponentName="Results")
walk.append({"step": "Results", "ok": hasattr(res, "GetSimulationResultFile")})

all_ok = all(item["ok"] for item in walk)
out = os.path.join(os.environ.get("TEMP", "C:/Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": all_ok, "walk": walk}))
f.close()
''')
        assert r.get("ok") is True, f"Workflow walk failed: {r}"
        assert len(r["walk"]) == 6
        for step in r["walk"]:
            assert step["ok"] is True, f"Step {step['step']} failed: {step}"
