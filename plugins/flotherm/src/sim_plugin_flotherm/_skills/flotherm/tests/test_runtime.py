"""Tests for the merged Flotherm driver (DriverProtocol + session lifecycle).

All tests use fakes/mocks. No real Flotherm required.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sim" / "src"))

from sim.drivers.flotherm.driver import FlothermDriver, NullBackend
from sim.drivers.flotherm._helpers import (
    find_installation, lint_floscript, lint_pack,
    build_solve_and_save, build_custom,
    detect_job_state, snapshot_result_files, collect_artifacts,
    extract_version, default_flouser, pack_project_dir,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_INSTALL = {
    "bat_path": r"C:\fake\flotherm.bat",
    "floserv_path": r"C:\fake\floserv.exe",
    "install_root": r"C:\fake",
    "version": "2504",
}

PATCH_INSTALL = patch("sim.drivers.flotherm.driver.find_installation", return_value=FAKE_INSTALL)
PATCH_GUI = patch.object(FlothermDriver, "_launch_gui", return_value=None)


class FakeBackend:
    def __init__(self, *, dispatch_ok=True):
        self._dispatch_ok = dispatch_ok
        self.dispatch_calls = []

    @property
    def name(self): return "fake"
    def can_execute(self): return True
    def dispatch(self, job, session):
        self.dispatch_calls.append(job["job_id"])
        if self._dispatch_ok:
            job["dispatch_metadata"]["dispatched_by"] = "fake"
            return True
        job["dispatch_metadata"]["rejected_by"] = "fake"
        return False


def _setup_project(workspace, proj_dir="TestProject.GUID123"):
    proj_path = os.path.join(workspace, proj_dir)
    for sc in ("msp_0", "msp_1"):
        end_dir = os.path.join(proj_path, "DataSets", "BaseSolution", sc, "end")
        os.makedirs(end_dir, exist_ok=True)
        for fn in ("Temperature", "Pressure", "Speed"):
            with open(os.path.join(end_dir, fn), "wb") as f:
                f.write(b"\x00" * 100)
    os.makedirs(os.path.join(proj_path, "PDProject"), exist_ok=True)
    return proj_dir


# ===========================================================================
# Bug regression tests
# ===========================================================================

class TestBug1_SnapshotPreserved:
    def test_null_backend_preserves_snapshot(self, tmp_path):
        proj_dir = _setup_project(str(tmp_path))
        with PATCH_INSTALL, PATCH_GUI:
            d = FlothermDriver()
            d.launch(workspace=str(tmp_path), ui_mode="headless")
            d.load_project(tmp_path / proj_dir)
            job = d.submit_job(label="test")
            assert "pre_solve_snapshot" in job["dispatch_metadata"]
            assert len(job["dispatch_metadata"]["pre_solve_snapshot"]) > 0


class TestBug2_StaleFloerrorLog:
    def test_stale_errors_filtered(self, tmp_path):
        proj_dir = _setup_project(str(tmp_path))
        stale = "ERROR E/11029 - old error\nERROR E/9012 - old\n"
        (tmp_path / "floerror.log").write_text(stale)

        field_dir = os.path.join(str(tmp_path), proj_dir, "DataSets", "BaseSolution")
        pre = snapshot_result_files(field_dir)
        time.sleep(0.05)
        with open(os.path.join(field_dir, "msp_0", "end", "Temperature"), "wb") as f:
            f.write(b"\xFF" * 200)

        state, reasons = detect_job_state(
            workspace=str(tmp_path), project_dir=proj_dir,
            pre_solve_snapshot=pre, process_pid=None,
            elapsed_s=10, timeout_s=300, floerror_baseline=stale,
        )
        assert state == "succeeded"


# ===========================================================================
# Session lifecycle
# ===========================================================================

class TestSessionLifecycle:
    def test_initial_state(self):
        assert FlothermDriver()._session is None

    def test_launch_ready(self, tmp_path):
        with PATCH_INSTALL, PATCH_GUI:
            d = FlothermDriver()
            s = d.launch(workspace=str(tmp_path), ui_mode="headless")
            assert s["state"] == "ready"

    def test_disconnect(self, tmp_path):
        with PATCH_INSTALL, PATCH_GUI:
            d = FlothermDriver()
            d.launch(workspace=str(tmp_path), ui_mode="headless")
            d.disconnect()
            assert d._session["state"] == "disconnected"

    def test_double_launch_raises(self, tmp_path):
        with PATCH_INSTALL, PATCH_GUI:
            d = FlothermDriver()
            d.launch(workspace=str(tmp_path), ui_mode="headless")
            with pytest.raises(RuntimeError, match="already active"):
                d.launch(workspace=str(tmp_path), ui_mode="headless")

    def test_reconnect(self, tmp_path):
        with PATCH_INSTALL, PATCH_GUI:
            d = FlothermDriver()
            d.launch(workspace=str(tmp_path), ui_mode="headless")
            d.disconnect()
            s = d.launch(workspace=str(tmp_path), ui_mode="headless")
            assert s["state"] == "ready"

    def test_not_installed(self):
        with patch("sim.drivers.flotherm.driver.find_installation", return_value=None):
            d = FlothermDriver()
            with pytest.raises(RuntimeError, match="not found"):
                d.launch()
            assert d._session["state"] == "launch_failed"

    def test_fields_populated(self, tmp_path):
        with PATCH_INSTALL, PATCH_GUI:
            d = FlothermDriver()
            s = d.launch(workspace=str(tmp_path), ui_mode="headless")
            assert s["session_id"]
            assert s["workspace"] == str(tmp_path)
            assert s["version"] == "2504"
            assert s["run_count"] == 0

    def test_submit_before_launch(self):
        with pytest.raises(RuntimeError, match="No active session"):
            FlothermDriver().submit_job(label="test")


# ===========================================================================
# Job state machine
# ===========================================================================

class TestJobStateMachine:
    @pytest.fixture
    def ready(self, tmp_path):
        proj_dir = _setup_project(str(tmp_path))
        with PATCH_INSTALL, PATCH_GUI:
            d = FlothermDriver()
            d.launch(workspace=str(tmp_path), ui_mode="headless")
            d.load_project(tmp_path / proj_dir)
            yield d
            d.disconnect()

    def test_null_backend_waiting(self, ready):
        job = ready.submit_job(label="test")
        assert job["state"] == "waiting_backend"

    def test_fake_backend_dispatched(self, tmp_path):
        proj_dir = _setup_project(str(tmp_path))
        fb = FakeBackend(dispatch_ok=True)
        with PATCH_INSTALL, PATCH_GUI:
            d = FlothermDriver(backend=fb)
            d.launch(workspace=str(tmp_path), ui_mode="headless")
            d.load_project(tmp_path / proj_dir)
            job = d.submit_job(label="test")
            assert job["state"] == "dispatched"
            assert len(fb.dispatch_calls) == 1

    def test_fake_backend_rejected(self, tmp_path):
        proj_dir = _setup_project(str(tmp_path))
        fb = FakeBackend(dispatch_ok=False)
        with PATCH_INSTALL, PATCH_GUI:
            d = FlothermDriver(backend=fb)
            d.launch(workspace=str(tmp_path), ui_mode="headless")
            d.load_project(tmp_path / proj_dir)
            job = d.submit_job(label="test")
            assert job["state"] == "waiting_backend"

    def test_run_count(self, ready):
        assert ready._session["run_count"] == 0
        ready.submit_job(label="j1")
        assert ready._session["run_count"] == 1
        ready.submit_job(label="j2")
        assert ready._session["run_count"] == 2

    def test_watch_waiting_returns_immediately(self, ready):
        job = ready.submit_job(label="test")
        watched = ready.watch_job(job["job_id"], timeout=1)
        assert watched["state"] == "waiting_backend"


# ===========================================================================
# Status detection
# ===========================================================================

class TestDetectJobState:
    def _make_fields(self, tmp_path, proj="proj"):
        d = os.path.join(str(tmp_path), proj, "DataSets", "BaseSolution", "msp_0", "end")
        os.makedirs(d, exist_ok=True)
        for fn in ("Temperature", "Pressure"):
            with open(os.path.join(d, fn), "wb") as f:
                f.write(b"\x00" * 50)
        return snapshot_result_files(os.path.join(str(tmp_path), proj, "DataSets", "BaseSolution"))

    def _modify(self, tmp_path, proj="proj"):
        time.sleep(0.05)
        p = os.path.join(str(tmp_path), proj, "DataSets", "BaseSolution", "msp_0", "end", "Temperature")
        with open(p, "wb") as f:
            f.write(b"\xFF" * 200)

    def _write_err(self, tmp_path, content):
        (tmp_path / "floerror.log").write_text(content)

    def test_succeeded(self, tmp_path):
        snap = self._make_fields(tmp_path)
        self._modify(tmp_path)
        s, _ = detect_job_state(workspace=str(tmp_path), project_dir="proj",
                                pre_solve_snapshot=snap, process_pid=None, elapsed_s=10, timeout_s=300)
        assert s == "succeeded"

    def test_failed(self, tmp_path):
        snap = self._make_fields(tmp_path)
        self._write_err(tmp_path, "ERROR E/11029 - fail\n")
        s, _ = detect_job_state(workspace=str(tmp_path), project_dir="proj",
                                pre_solve_snapshot=snap, process_pid=None, elapsed_s=10, timeout_s=300)
        assert s == "failed"

    def test_timeout(self, tmp_path):
        snap = self._make_fields(tmp_path)
        s, _ = detect_job_state(workspace=str(tmp_path), project_dir="proj",
                                pre_solve_snapshot=snap, process_pid=None, elapsed_s=300, timeout_s=300)
        assert s == "timeout"

    def test_unknown(self, tmp_path):
        snap = self._make_fields(tmp_path)
        s, _ = detect_job_state(workspace=str(tmp_path), project_dir="proj",
                                pre_solve_snapshot=snap, process_pid=None, elapsed_s=10, timeout_s=300)
        assert s == "unknown"

    def test_empty_snapshot_no_false_positive(self, tmp_path):
        self._make_fields(tmp_path)
        s, _ = detect_job_state(workspace=str(tmp_path), project_dir="proj",
                                pre_solve_snapshot={}, process_pid=None, elapsed_s=10, timeout_s=300)
        assert s != "succeeded"


# ===========================================================================
# Script builder → lint round-trip
# ===========================================================================

class TestScriptBuilderLint:
    def test_solve_and_save(self, tmp_path):
        xml = build_solve_and_save("TestProject")
        f = tmp_path / "solve.xml"
        f.write_text(xml, encoding="utf-8")
        assert lint_floscript(f).ok is True

    def test_custom(self, tmp_path):
        xml = build_custom([
            {"command": "project_load", "attrs": {"project_name": "Test"}},
            {"command": "start", "attrs": {"start_type": "solver"}},
        ])
        f = tmp_path / "custom.xml"
        f.write_text(xml, encoding="utf-8")
        assert lint_floscript(f).ok is True


# ===========================================================================
# Driver/runtime consistency
# ===========================================================================

class TestDriverConsistency:
    def test_xml_no_not_implemented(self, tmp_path):
        xml = tmp_path / "test.xml"
        xml.write_text('<?xml version="1.0"?>\n<xml_log_file version="1.0"><start start_type="solver"/></xml_log_file>\n')
        with PATCH_INSTALL, PATCH_GUI:
            result = FlothermDriver().run_file(xml)
            assert "waiting_backend" in result.stdout

    def test_pack_structured_result(self, tmp_path):
        import zipfile
        pack = tmp_path / "test.pack"
        with zipfile.ZipFile(pack, "w") as z:
            z.writestr("Proj.GUID/PDProject/group", "data")
            z.writestr("Proj.GUID/DataSets/BaseSolution/msp_0/end/Temperature", "x")
        with PATCH_INSTALL, PATCH_GUI:
            result = FlothermDriver().run_file(pack)
            assert "state:" in result.stdout
            assert result.solver == "flotherm"


# ===========================================================================
# Install / version helpers
# ===========================================================================

class TestInstall:
    def test_version_standard(self):
        assert extract_version(r"C:\Siemens\SimcenterFlotherm\2504\WinXP\bin") == "2504"

    def test_version_env(self, monkeypatch):
        monkeypatch.setenv("FLOTHERM_VERSION", "9999")
        assert extract_version(r"C:\whatever") == "9999"

    def test_version_none(self, monkeypatch):
        monkeypatch.delenv("FLOTHERM_VERSION", raising=False)
        assert extract_version(r"C:\no\version") is None

    def test_flouser_env(self, monkeypatch):
        monkeypatch.setenv("FLOUSERDIR", r"D:\custom")
        assert default_flouser(r"C:\fake") == r"D:\custom"

    def test_flouser_default(self, monkeypatch):
        monkeypatch.delenv("FLOUSERDIR", raising=False)
        assert default_flouser(r"C:\fake").endswith("flouser")

    def test_pack_multi_toplevel(self, tmp_path):
        import zipfile
        pack = tmp_path / "multi.pack"
        with zipfile.ZipFile(pack, "w") as z:
            z.writestr("B.GUID/x", "b")
            z.writestr("A.GUID/x", "a")
        assert pack_project_dir(pack) == "A.GUID"

    def test_pack_corrupt(self, tmp_path):
        bad = tmp_path / "bad.pack"
        bad.write_bytes(b"not a zip")
        assert pack_project_dir(bad) is None
