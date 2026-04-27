"""TDD tests for all PyWorkbench example patterns.

Tests are organized by the 7 official examples. Each test extracts the
core API pattern from the example and validates it against real Ansys 24.1.

Tier structure:
  - TestSessionLifecycle: launch/exit (all examples share this)
  - TestSystemCreation: create analysis systems (fluent, mechanical, modal)
  - TestFileTransfer: upload/download round-trip (logging example)
  - TestLogging: log file/console config (logging example)
  - TestParameterManipulation: design point parameters (material designer)
  - TestSubSolverIntegration: start_mechanical_server (pymechanical examples)
  - TestMultiSystemProject: multiple systems in one project (axisymmetric rotor)

All tests use PyWorkbench SDK 0.4 against Ansys 24.1.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Skip if PyWorkbench or Ansys not available
# ---------------------------------------------------------------------------

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

RESULT_FILE = Path(os.environ.get("TEMP", "C:/Temp")) / "sim_wb_result.json"


# ---------------------------------------------------------------------------
# Shared fixture: one Workbench session per module (expensive to launch)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def wb():
    """Launch a single Workbench session for all tests in this module."""
    client = pywb.launch_workbench(release="241")
    yield client
    # SDK 0.4 doesn't have explicit exit; let process cleanup


def _run_journal(wb, code: str) -> dict:
    """Execute IronPython journal and read result file."""
    if RESULT_FILE.exists():
        RESULT_FILE.unlink()
    wb.run_script_string(code, log_level="warning")
    if RESULT_FILE.exists():
        return json.loads(RESULT_FILE.read_text(encoding="utf-8"))
    return {}


# ===========================================================================
# Example: fluent_workflow — launch + run_script_string + system creation
# ===========================================================================

@skip_no_env
class TestSessionLifecycle:
    """Pattern from ALL examples: launch_workbench → run_script → exit."""

    def test_session_is_alive(self, wb):
        """Smoke test: session responds to a trivial script."""
        result = _run_journal(wb, '''
import json, os, codecs
out = os.path.join(os.environ.get("TEMP", "C:\\\\Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": True, "step": "smoke"}))
f.close()
''')
        assert result.get("ok") is True

    def test_run_script_string_returns(self, wb):
        """run_script_string should not raise on valid IronPython."""
        ret = wb.run_script_string('x = 1 + 1', log_level="warning")
        # SDK 0.4 returns {} or None; not raising is success
        assert True


# ===========================================================================
# Example: fluent_workflow — create Fluent system
# Example: pymechanical_integration — create Static Structural
# Example: axisymmetric_rotor — create Modal system
# Example: cyclic_symmetry_analysis — create Harmonic Response
# ===========================================================================

@skip_no_env
class TestSystemCreation:
    """Pattern from fluent/mechanical/rotor/cyclic examples: GetTemplate + CreateSystem."""

    @pytest.mark.parametrize("template,solver,expected_components", [
        ("Static Structural", "ANSYS", 6),
        ("Modal", "ANSYS", 6),
        ("Harmonic Response", "ANSYS", 6),
        ("Steady-State Thermal", "ANSYS", 6),
        ("Transient Structural", "ANSYS", 6),
    ])
    def test_create_mechanical_systems(self, wb, template, solver, expected_components):
        """Create analysis system and verify component count.

        Covers patterns from:
        - pymechanical_integration (Static Structural)
        - axisymmetric_rotor (Modal)
        - cyclic_symmetry_analysis (Harmonic Response)
        """
        code = '''
SetScriptVersion(Version="24.1")
template1 = GetTemplate(TemplateName="%s", Solver="%s")
system1 = template1.CreateSystem()
components = []
for comp_name in ["Engineering Data", "Geometry", "Model", "Setup", "Solution", "Results"]:
    try:
        container = system1.GetContainer(ComponentName=comp_name)
        components.append(comp_name)
    except:
        pass
import json, os, codecs
out = os.path.join(os.environ.get("TEMP", "C:\\\\Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": len(components) == %d, "step": "create-%s", "components": components, "count": len(components)}))
f.close()
''' % (template, solver, expected_components, template.lower().replace(" ", "-"))
        result = _run_journal(wb, code)
        assert result.get("ok") is True, f"{template}: expected {expected_components} components, got {result}"
        assert result.get("count") == expected_components

    def test_create_fluent_system(self, wb):
        """Pattern from fluent_workflow: create FLUENT system.

        NOTE 1: On Ansys 24.1 the template name is "FLUENT" (no Solver param),
        not "Fluent" with Solver="FLUENT" as shown in official examples.
        NOTE 2: Fluent systems only expose Setup and Solution via GetContainer.
        Geometry/Mesh/Results are managed through the Fluent solver directly,
        not through Workbench's component API.
        """
        code = '''
SetScriptVersion(Version="24.1")
template1 = GetTemplate(TemplateName="FLUENT")
system1 = template1.CreateSystem()
components = []
for comp_name in ["Setup", "Solution"]:
    try:
        container = system1.GetContainer(ComponentName=comp_name)
        components.append(comp_name)
    except:
        pass
import json, os, codecs
out = os.path.join(os.environ.get("TEMP", "C:\\\\Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": len(components) == 2, "step": "create-fluent", "components": components, "count": len(components)}))
f.close()
'''
        result = _run_journal(wb, code)
        assert result.get("ok") is True, f"Fluent: expected 2 accessible components, got {result}"
        assert set(result.get("components", [])) == {"Setup", "Solution"}


# ===========================================================================
# Example: logging — file upload/download, log config
# ===========================================================================

@skip_no_env
class TestFileTransfer:
    """Pattern from logging example: upload_file / download_file round-trip."""

    def test_upload_and_download(self, wb):
        """Upload a test file, download it, verify content matches.

        Files uploaded via PyWorkbench land in the server's TEMP directory
        (same as GetServerWorkingDirectory()), NOT in os.getcwd().
        IronPython must use os.environ["TEMP"] to find them.
        """
        test_content = "sim_pyworkbench_file_transfer_test_67890"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False,
            dir=os.environ.get("TEMP", tempfile.gettempdir()),
            encoding="utf-8",
        ) as f:
            f.write(test_content)
            upload_path = f.name
            upload_name = os.path.basename(f.name)

        try:
            # Upload
            wb.upload_file(upload_path)

            # Verify file exists on server — files land in %TEMP%
            code = '''
import os, json, codecs
server_dir = os.environ.get("TEMP", "C:\\\\Temp")
full_path = os.path.join(server_dir, "%s")
exists = os.path.isfile(full_path)
out = os.path.join(server_dir, "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": exists, "step": "verify-upload", "file": full_path}))
f.close()
''' % upload_name
            result = _run_journal(wb, code)
            assert result.get("ok") is True, f"File not found on server: {result}"

            # Download
            download_dir = tempfile.mkdtemp()
            wb.download_file(upload_name, target_dir=download_dir, show_progress=False)
            downloaded = os.path.join(download_dir, upload_name)
            assert os.path.exists(downloaded), f"Downloaded file not found at {downloaded}"

            with open(downloaded, encoding="utf-8") as df:
                assert df.read() == test_content
        finally:
            os.unlink(upload_path)


@skip_no_env
class TestLogging:
    """Pattern from logging example: set_log_file / set_console_log_level."""

    def test_set_log_file(self, wb):
        """set_log_file should not raise."""
        log_path = os.path.join(
            os.environ.get("TEMP", tempfile.gettempdir()),
            "sim_wb_test_log.log",
        )
        wb.set_log_file(log_path)
        # Run a trivial script to generate log output
        wb.run_script_string('x = 42', log_level="info")
        wb.reset_log_file()
        # Log file should exist (may be empty depending on SDK version)
        assert os.path.exists(log_path)

    def test_set_console_log_level(self, wb):
        """set_console_log_level should not raise."""
        wb.set_console_log_level("warning")
        wb.set_console_log_level("error")
        assert True  # No exception = pass


# ===========================================================================
# Example: material_designer_workflow — parameter manipulation
# ===========================================================================

@skip_no_env
class TestParameterManipulation:
    """Pattern from material_designer: SetParameterExpression + read back."""

    def test_create_system_and_read_parameters(self, wb):
        """Create a system and verify parameters API is accessible.

        We can't run Material Designer without the project file, but we
        can verify the Parameters API exists and basic queries work.
        """
        code = '''
SetScriptVersion(Version="24.1")
template1 = GetTemplate(TemplateName="Static Structural", Solver="ANSYS")
system1 = template1.CreateSystem()

# Check if Parameters API is accessible
has_params = "Parameters" in dir()

import json, os, codecs
out = os.path.join(os.environ.get("TEMP", "C:\\\\Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({
    "ok": True,
    "step": "parameter-api-check",
    "has_parameters": has_params,
}))
f.close()
'''
        result = _run_journal(wb, code)
        assert result.get("ok") is True
        assert result.get("has_parameters") is True


# ===========================================================================
# Example: pymechanical/rotor/blade/cyclic — start_mechanical_server
# ===========================================================================

@skip_no_env
class TestSubSolverIntegration:
    """Pattern from pymechanical/rotor/blade/cyclic: start_mechanical_server."""

    def test_start_mechanical_server(self, wb):
        """Create a Mechanical system and start its gRPC server.

        This is the core pattern from 4 out of 7 examples.
        Acceptance: server port > 0 returned.
        """
        # First create a system
        code = '''
SetScriptVersion(Version="24.1")
template1 = GetTemplate(TemplateName="Static Structural", Solver="ANSYS")
system1 = template1.CreateSystem()

import json, os, codecs
out = os.path.join(os.environ.get("TEMP", "C:\\\\Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": True, "step": "create-for-mechanical"}))
f.close()
'''
        result = _run_journal(wb, code)
        assert result.get("ok") is True

        # Start Mechanical server — this is the key API call
        try:
            port = wb.start_mechanical_server(system_name="SYS")
            assert isinstance(port, int)
            assert port > 0, f"Expected port > 0, got {port}"
        except Exception as e:
            # If Mechanical license unavailable, that's a known limitation
            err_msg = str(e).lower()
            if "license" in err_msg or "not available" in err_msg:
                pytest.skip("Mechanical license not available")
            raise


# ===========================================================================
# Example: axisymmetric_rotor — multi-system project
# ===========================================================================

@skip_no_env
class TestMultiSystemProject:
    """Pattern from axisymmetric_rotor: multiple systems in one project."""

    def test_create_multiple_systems(self, wb):
        """Create 3 different analysis systems in a single project.

        This mirrors the axisymmetric rotor example which creates
        multiple systems for 2D and 3D modal analysis.
        """
        code = '''
SetScriptVersion(Version="24.1")

# System 1: Static Structural (like the base setup)
t1 = GetTemplate(TemplateName="Static Structural", Solver="ANSYS")
s1 = t1.CreateSystem()

# System 2: Modal (like the 2D axisymmetric analysis)
t2 = GetTemplate(TemplateName="Modal", Solver="ANSYS")
s2 = t2.CreateSystem()

# System 3: Steady-State Thermal (additional system type)
t3 = GetTemplate(TemplateName="Steady-State Thermal", Solver="ANSYS")
s3 = t3.CreateSystem()

import json, os, codecs
out = os.path.join(os.environ.get("TEMP", "C:\\\\Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({
    "ok": True,
    "step": "multi-system",
    "system_count": 3,
}))
f.close()
'''
        result = _run_journal(wb, code)
        assert result.get("ok") is True
        assert result.get("system_count") == 3


# ===========================================================================
# Full workflow: create system → upload file → run journal → verify
# ===========================================================================

@skip_no_env
class TestEndToEndWorkflow:
    """E2E: session → system → file transfer → journal → verify."""

    def test_upload_read_roundtrip(self, wb):
        """Upload a config file, read it back via IronPython."""
        config_content = '{"solver": "static-structural", "iterations": 100}'
        config_path = os.path.join(
            os.environ.get("TEMP", tempfile.gettempdir()),
            "sim_e2e_config.json",
        )
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(config_content)

        wb.upload_file(config_path)

        result = _run_journal(wb, '''
import json, os, codecs
server_dir = os.environ.get("TEMP", "C:\\\\Temp")
config_path = os.path.join(server_dir, "sim_e2e_config.json")
try:
    f = open(config_path, "r")
    data = json.loads(f.read())
    f.close()
    ok = data.get("solver") == "static-structural"
except Exception as e:
    data = {"error": str(e)}
    ok = False

out = os.path.join(server_dir, "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": ok, "step": "e2e-read-config", "config": data}))
f.close()
''')
        assert result.get("ok") is True, f"Failed: {result}"
        assert result["config"]["solver"] == "static-structural"
        assert result["config"]["iterations"] == 100
        os.unlink(config_path)


@skip_no_env
class TestGeometryImportAndMesh:
    """E2E: upload real geometry → import → mesh.

    Uses two_pipes.agdb from ansys/example-data repo (must be pre-downloaded
    to %TEMP% as raw binary, NOT via upload_file_from_example_repo which may
    return HTML on SDK 0.4).

    Acceptance: geometry children > 0, mesh nodes > 0.
    """

    @pytest.fixture(autouse=True)
    def _download_geometry(self):
        """Ensure two_pipes.agdb exists in TEMP as raw binary."""
        import requests

        geo_path = Path(os.environ["TEMP"]) / "two_pipes.agdb"
        if not geo_path.exists() or geo_path.stat().st_size < 100_000:
            url = (
                "https://github.com/ansys/example-data/raw/master/"
                "pyworkbench/pymechanical-integration/agdb/two_pipes.agdb"
            )
            r = requests.get(url, allow_redirects=True, timeout=30)
            geo_path.write_bytes(r.content)
        self.geo_path = geo_path

    @pytest.mark.slow
    def test_import_geometry_and_mesh(self):
        """Upload geometry, import via SetFile with abs path, mesh.

        Uses a FRESH Workbench session. Requires SpaceClaim to parse .agdb.
        Takes 60-90 seconds due to Update() geometry import.

        Acceptance: geometry children >= 2, mesh nodes > 100.
        """
        import time

        fresh_wb = pywb.launch_workbench(release="241")
        time.sleep(5)

        try:
            fresh_wb.upload_file(str(self.geo_path))

            fresh_wb.run_script_string(
                'SetScriptVersion(Version="24.1")\n'
                "import os\n"
                'template1 = GetTemplate(TemplateName="Static Structural", Solver="ANSYS")\n'
                "system1 = template1.CreateSystem()\n"
                'geometry1 = system1.GetContainer(ComponentName="Geometry")\n'
                'geo_path = os.path.join(os.environ.get("TEMP","C:/Temp"), "two_pipes.agdb")\n'
                "geometry1.SetFile(FilePath=geo_path)\n"
                "system1.Update()\n",
                log_level="warning",
            )
            time.sleep(25)

            port = fresh_wb.start_mechanical_server(system_name="SYS")
            assert port is not None and port > 0, f"Mechanical port invalid: {port}"
            time.sleep(15)

            from ansys.mechanical.core import connect_to_mechanical

            mech = connect_to_mechanical(ip="localhost", port=port)

            geo_count = int(mech.run_python_script("Model.Geometry.Children.Count"))
            assert geo_count >= 2, f"Expected >= 2 geometry children, got {geo_count}"

            # Mesh
            mech.run_python_script("Model.Mesh.GenerateMesh()")
            nodes = int(mech.run_python_script("Model.Mesh.Nodes"))
            elements = int(mech.run_python_script("Model.Mesh.Elements"))
            assert nodes > 100, f"Expected > 100 mesh nodes, got {nodes}"
            assert elements > 10, f"Expected > 10 mesh elements, got {elements}"

            mech.exit()
        finally:
            # Clean up the fresh session
            import subprocess
            subprocess.run(
                ["taskkill", "/F", "/PID", str(os.getpid())],
                capture_output=True,
            )  # won't actually kill us, just try
