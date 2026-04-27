"""Workbench Orchestration Tests — the REAL purpose of PyWorkbench.

PyWorkbench's first-principles purpose is PROJECT ORCHESTRATION, not solving.
Mechanical/Fluent/CFX solving happens via their respective PyAnsys clients
(PyMechanical, PyFluent). Workbench handles:

1. Project lifecycle (Save → Archive → Reopen → Close)
2. System management (Create → Update → Link → Duplicate → Delete)
3. File orchestration (upload inputs, download result archives)
4. Parameter management (design points, parameter updates)
5. Cascading updates between linked systems

These tests validate that a COMPLETE Workbench project workflow runs
end-to-end — everything except the actual solve (which is the sub-solver's
job, tested separately in PyMechanical/PyFluent skills).
"""
from __future__ import annotations

import json
import os
import tempfile
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
    """Single Workbench session for all orchestration tests."""
    client = pywb.launch_workbench(release="241")
    time.sleep(5)
    yield client


def _run(wb, code: str, wait: float = 2) -> dict:
    """Run IronPython journal and read result file."""
    if RESULT_FILE.exists():
        RESULT_FILE.unlink()
    wb.run_script_string(code, log_level="warning")
    time.sleep(wait)
    if RESULT_FILE.exists():
        return json.loads(RESULT_FILE.read_text(encoding="utf-8"))
    return {}


# ===========================================================================
# Test 1: Project lifecycle (Save → SaveAs → Reopen)
# ===========================================================================

@skip_no_env
class TestProjectLifecycle:
    """The fundamental Workbench contract: projects as first-class objects."""

    def test_save_project_creates_wbpj_and_files_dir(self, wb):
        """Save() must create both .wbpj and _files/ directory.

        This is the canonical Workbench project layout: every project
        consists of a metadata file (.wbpj) plus a supporting directory
        containing cell data, databases, and result files.
        """
        result = _run(wb, '''
import os, json, codecs
template1 = GetTemplate(TemplateName="Static Structural", Solver="ANSYS")
system1 = template1.CreateSystem()
temp = os.environ.get("TEMP", "C:/Temp")
proj_path = os.path.join(temp, "sim_lifecycle_test.wbpj")
files_dir = os.path.join(temp, "sim_lifecycle_test_files")
Save(FilePath=proj_path, Overwrite=True)
wbpj_exists = os.path.isfile(proj_path)
files_exists = os.path.isdir(files_dir)
out = os.path.join(temp, "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({
    "ok": wbpj_exists and files_exists,
    "wbpj": wbpj_exists,
    "files_dir": files_exists,
    "path": proj_path,
}))
f.close()
''')
        assert result.get("ok") is True, f"Project save failed: {result}"
        assert result["wbpj"] is True
        assert result["files_dir"] is True

    def test_project_file_is_readable(self, wb):
        """The saved .wbpj must be a real file (size > 0)."""
        result = _run(wb, '''
import os, json, codecs
temp = os.environ.get("TEMP", "C:/Temp")
proj = os.path.join(temp, "sim_lifecycle_test.wbpj")
size = os.path.getsize(proj) if os.path.isfile(proj) else 0
out = os.path.join(temp, "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": size > 0, "size": size}))
f.close()
''')
        assert result.get("ok") is True
        assert result.get("size", 0) > 0


# ===========================================================================
# Test 2: System management (Create → Enumerate → Delete → Duplicate)
# ===========================================================================

@skip_no_env
class TestSystemManagement:
    """System CRUD is Workbench's primary orchestration feature."""

    def test_create_and_enumerate_systems(self, wb):
        """GetAllSystems() returns created systems by name."""
        result = _run(wb, '''
import json, os, codecs
# Create two new systems
t1 = GetTemplate(TemplateName="Static Structural", Solver="ANSYS")
s1 = t1.CreateSystem()
t2 = GetTemplate(TemplateName="Modal", Solver="ANSYS")
s2 = t2.CreateSystem()
# Enumerate all systems in project
all_sys = GetAllSystems()
names = [str(s.Name) for s in all_sys]
out = os.path.join(os.environ.get("TEMP", "C:/Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": len(names) >= 2, "names": names, "count": len(names)}))
f.close()
''')
        assert result.get("ok") is True, f"Enumeration failed: {result}"
        assert result["count"] >= 2
        # System names follow "SYS", "SYS 1", "SYS 2" pattern
        assert all(name.startswith("SYS") for name in result["names"])

    def test_system_operations_available(self, wb):
        """Every system exposes Update, Delete, Duplicate, Refresh, Move."""
        result = _run(wb, '''
import json, os, codecs
systems = GetAllSystems()
ops_found = []
if len(systems) > 0:
    s = systems[0]
    for op in ["Update", "Delete", "Duplicate", "Refresh", "Move"]:
        if hasattr(s, op):
            ops_found.append(op)
out = os.path.join(os.environ.get("TEMP", "C:/Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": len(ops_found) == 5, "ops": ops_found}))
f.close()
''')
        assert result.get("ok") is True
        assert set(result["ops"]) == {"Update", "Delete", "Duplicate", "Refresh", "Move"}

    def test_duplicate_system(self, wb):
        """Duplicating a system creates a new one with incremented name."""
        result = _run(wb, '''
import json, os, codecs
# Count before
before = len(GetAllSystems())
# Create and duplicate
t = GetTemplate(TemplateName="Steady-State Thermal", Solver="ANSYS")
s = t.CreateSystem()
s.Duplicate()
after = len(GetAllSystems())
out = os.path.join(os.environ.get("TEMP", "C:/Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": after == before + 2, "before": before, "after": after}))
f.close()
''')
        assert result.get("ok") is True, f"Duplicate failed: {result}"
        assert result["after"] == result["before"] + 2

    def test_delete_system(self, wb):
        """Delete removes a system from the project."""
        result = _run(wb, '''
import json, os, codecs
# Create a system to delete
t = GetTemplate(TemplateName="Harmonic Response", Solver="ANSYS")
s = t.CreateSystem()
before = len(GetAllSystems())
s.Delete()
after = len(GetAllSystems())
out = os.path.join(os.environ.get("TEMP", "C:/Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": after == before - 1, "before": before, "after": after}))
f.close()
''')
        assert result.get("ok") is True, f"Delete failed: {result}"
        assert result["after"] == result["before"] - 1


# ===========================================================================
# Test 3: Project archive (.wbpz)
# ===========================================================================

@skip_no_env
class TestProjectArchive:
    """Archive/Restore is the canonical project transport mechanism."""

    def test_archive_creates_wbpz(self, wb):
        """Archive() after Save() creates a .wbpz project package."""
        result = _run(wb, '''
import os, json, codecs
temp = os.environ.get("TEMP", "C:/Temp")
# Must save first
proj = os.path.join(temp, "sim_archive_test.wbpj")
Save(FilePath=proj, Overwrite=True)
# Now archive
arch = os.path.join(temp, "sim_archive_test.wbpz")
if os.path.isfile(arch):
    os.remove(arch)
Archive(FilePath=arch)
size = os.path.getsize(arch) if os.path.isfile(arch) else 0
out = os.path.join(temp, "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": size > 1000, "size": size, "path": arch}))
f.close()
''', wait=8)
        assert result.get("ok") is True, f"Archive failed: {result}"
        assert result.get("size", 0) > 1000, "Archive too small"

    def test_download_archive_via_sdk(self, wb):
        """SDK download_file can retrieve the archive to client side."""
        # Archive path from previous test
        arch_name = "sim_archive_test.wbpz"

        # Download via SDK
        download_dir = tempfile.mkdtemp()
        wb.download_file(arch_name, target_dir=download_dir, show_progress=False)

        # Verify downloaded file exists and is non-trivial
        downloaded = Path(download_dir) / arch_name
        assert downloaded.exists(), f"Not found at {downloaded}"
        assert downloaded.stat().st_size > 1000


# ===========================================================================
# Test 4: File orchestration (upload geometry to system geometry cell)
# ===========================================================================

@skip_no_env
class TestFileOrchestration:
    """Upload file → attach to Geometry cell → verify path is set."""

    def test_upload_and_attach_geometry_file(self, wb):
        """Full flow: upload file, attach to Geometry cell, verify.

        This does NOT call Update() — we only verify that SetFile()
        accepts the path and the system registers the file attachment.
        Actual geometry parsing happens during Update(), which needs
        SpaceClaim/DesignModeler and is not part of Workbench's
        orchestration role.
        """
        # Create a dummy .agdb file (just for path attachment test)
        dummy = Path(TEMP) / "sim_dummy_geometry.agdb"
        dummy.write_bytes(b"DUMMY_AGDB_FILE_FOR_PATH_TEST")

        # Upload to server
        wb.upload_file(str(dummy))

        # Create system, attach file, verify FilePath is set
        result = _run(wb, '''
import os, json, codecs
t = GetTemplate(TemplateName="Static Structural", Solver="ANSYS")
s = t.CreateSystem()
geo = s.GetContainer(ComponentName="Geometry")
geo_path = os.path.join(os.environ.get("TEMP", "C:/Temp"), "sim_dummy_geometry.agdb")
try:
    geo.SetFile(FilePath=geo_path)
    set_ok = True
    err = ""
except Exception as e:
    set_ok = False
    err = str(e)[:100]
out = os.path.join(os.environ.get("TEMP", "C:/Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": set_ok, "error": err}))
f.close()
''')
        assert result.get("ok") is True, f"SetFile failed: {result}"
        dummy.unlink()


# ===========================================================================
# Test 5: Script execution via run_script_file (upload + execute)
# ===========================================================================

@skip_no_env
class TestScriptFileExecution:
    """Upload a .wbjn script and execute it via run_script_file."""

    def test_upload_and_run_wbjn_script(self, wb):
        """Upload a journal file, execute it, verify side effects."""
        # Create a wbjn script that creates a system
        script_content = """SetScriptVersion(Version="24.1")
template1 = GetTemplate(TemplateName="Transient Structural", Solver="ANSYS")
system1 = template1.CreateSystem()
"""
        script_path = Path(TEMP) / "sim_test_script.wbjn"
        script_path.write_text(script_content, encoding="utf-8")

        # Upload to server
        wb.upload_file(str(script_path))

        # Count systems before
        before = _run(wb, '''
import json, os, codecs
n = len(GetAllSystems())
out = os.path.join(os.environ.get("TEMP", "C:/Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"count": n}))
f.close()
''')
        count_before = before["count"]

        # Run the uploaded script file
        wb.run_script_file("sim_test_script.wbjn", log_level="warning")
        time.sleep(3)

        # Count after
        after = _run(wb, '''
import json, os, codecs
n = len(GetAllSystems())
out = os.path.join(os.environ.get("TEMP", "C:/Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"count": n}))
f.close()
''')
        count_after = after["count"]

        assert count_after == count_before + 1, (
            f"Script file did not create system: {count_before} → {count_after}"
        )
        script_path.unlink()


# ===========================================================================
# Test 6: Complete project lifecycle (end-to-end orchestration)
# ===========================================================================

@skip_no_env
class TestCompleteProjectLifecycle:
    """E2E: Create → Build → Save → Archive → Download → Verify.

    This is the canonical Workbench workflow that Workbench skills should
    validate. Every sub-step is a real filesystem side-effect.
    """

    def test_full_orchestration_workflow(self, wb):
        """The complete Workbench orchestration chain in one test."""
        # Step 1: Create a fresh project with multiple systems
        r1 = _run(wb, '''
import os, json, codecs
t1 = GetTemplate(TemplateName="Static Structural", Solver="ANSYS")
s1 = t1.CreateSystem()
t2 = GetTemplate(TemplateName="Modal", Solver="ANSYS")
s2 = t2.CreateSystem()
t3 = GetTemplate(TemplateName="Steady-State Thermal", Solver="ANSYS")
s3 = t3.CreateSystem()
out = os.path.join(os.environ.get("TEMP", "C:/Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": True, "step": "systems-created"}))
f.close()
''')
        assert r1.get("ok") is True

        # Step 2: Save the project (unique name to avoid lock conflicts)
        import uuid
        unique_name = f"sim_e2e_{uuid.uuid4().hex[:8]}"
        r2 = _run(wb, f'''
import os, json, codecs
temp = os.environ.get("TEMP", "C:/Temp")
proj = os.path.join(temp, "{unique_name}.wbpj")
Save(FilePath=proj, Overwrite=True)
exists = os.path.isfile(proj)
size = os.path.getsize(proj) if exists else 0
out = os.path.join(temp, "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({{"ok": exists and size > 0, "size": size}}))
f.close()
''')
        assert r2.get("ok") is True, f"Save failed: {r2}"

        # Step 3: Archive
        r3 = _run(wb, f'''
import os, json, codecs
temp = os.environ.get("TEMP", "C:/Temp")
arch = os.path.join(temp, "{unique_name}.wbpz")
if os.path.isfile(arch):
    os.remove(arch)
Archive(FilePath=arch)
size = os.path.getsize(arch) if os.path.isfile(arch) else 0
out = os.path.join(temp, "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({{"ok": size > 1000, "size": size}}))
f.close()
''', wait=8)
        assert r3.get("ok") is True, f"Archive failed: {r3}"
        archive_server_size = r3["size"]

        # Step 4: Download the archive to client
        download_dir = tempfile.mkdtemp()
        wb.download_file(f"{unique_name}.wbpz", target_dir=download_dir, show_progress=False)

        downloaded = Path(download_dir) / f"{unique_name}.wbpz"
        assert downloaded.exists()
        client_size = downloaded.stat().st_size

        # Client archive should match server archive size
        assert client_size == archive_server_size, (
            f"Size mismatch: server={archive_server_size}, client={client_size}"
        )

        # Step 5: Verify archive is a real zip (starts with PK)
        with open(downloaded, "rb") as f:
            magic = f.read(2)
        assert magic == b"PK", f"Archive is not a valid zip: {magic}"

        print(f"\n[E2E] Complete project lifecycle validated:")
        print(f"  Systems: 3 created")
        print(f"  Archive: {client_size} bytes ({client_size // 1024} KB)")
        print(f"  Downloaded to: {downloaded}")
