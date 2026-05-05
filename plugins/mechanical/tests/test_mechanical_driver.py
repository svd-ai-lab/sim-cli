"""Tier 1 protocol-compliance tests for the Mechanical driver."""
from __future__ import annotations

from pathlib import Path

import pytest

from sim_plugin_mechanical import MechanicalDriver

FIXTURES = Path(__file__).parent.parent / "fixtures"


class TestDetect:
    def setup_method(self):
        self.driver = MechanicalDriver()

    def test_good_extapi(self):
        assert self.driver.detect(FIXTURES / "mechanical_good.py") is True

    def test_sdk_import(self):
        assert self.driver.detect(FIXTURES / "mechanical_sdk_import.py") is True

    def test_no_markers(self):
        assert self.driver.detect(FIXTURES / "mechanical_no_markers.py") is False

    def test_wrong_suffix(self):
        assert self.driver.detect(FIXTURES / "not_simulation.py") is False

    def test_missing(self):
        assert self.driver.detect(Path("/no/such.py")) is False


class TestLint:
    def setup_method(self):
        self.driver = MechanicalDriver()

    def test_good(self):
        assert self.driver.lint(FIXTURES / "mechanical_good.py").ok is True

    def test_sdk_import(self):
        assert self.driver.lint(FIXTURES / "mechanical_sdk_import.py").ok is True

    def test_no_markers_warn(self):
        r = self.driver.lint(FIXTURES / "mechanical_no_markers.py")
        assert r.ok is True
        assert any(d.level == "warning" for d in r.diagnostics)

    def test_syntax_error(self):
        assert self.driver.lint(FIXTURES / "mechanical_syntax_error.py").ok is False


class TestConnect:
    def test_not_installed(self, monkeypatch):
        d = MechanicalDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [])
        info = d.connect()
        assert info.status == "not_installed"

    def test_found_no_sdk(self, monkeypatch):
        from sim.driver import SolverInstall
        import sim_plugin_mechanical.driver as drv
        d = MechanicalDriver()
        monkeypatch.setattr(
            d, "detect_installed",
            lambda: [SolverInstall(
                name="mechanical", version="24.1",
                path="C:/Program Files/ANSYS Inc/v241",
                source="test",
                extra={"exe": "C:/Program Files/ANSYS Inc/v241/aisol/bin/winx64/AnsysWBU.exe"},
            )],
        )
        # Force PyMechanical missing.
        monkeypatch.setattr(drv, "_try_import_pymechanical", lambda: None)
        info = d.connect()
        assert info.status == "error"
        assert "ansys-mechanical-core" in info.message


class TestParseOutput:
    def setup_method(self):
        self.driver = MechanicalDriver()

    def test_last_json(self):
        stdout = 'banner\n{"n_analyses": 2, "ok": true}\n'
        out = self.driver.parse_output(stdout)
        assert out["n_analyses"] == 2
        assert out["ok"] is True

    def test_no_json(self):
        assert self.driver.parse_output("nope") == {}

    def test_empty(self):
        assert self.driver.parse_output("") == {}


class TestRunFile:
    def test_raises_when_not_installed(self, monkeypatch):
        d = MechanicalDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [])
        # If PyMechanical is not importable in the test env, the
        # _try_import_pymechanical guard fires first; if it is, the
        # detect_installed guard fires next. Either way the driver must
        # raise before contacting Mechanical.
        with pytest.raises(RuntimeError):
            d.run_file(FIXTURES / "mechanical_good.py")


# --- helpers used by launch-kwargs tests below -----------------------------

def _fake_install(version: str = "25.2"):
    from sim.driver import SolverInstall
    return SolverInstall(
        name="mechanical", version=version,
        path=f"C:/Program Files/ANSYS Inc/v{version.replace('.', '')}",
        source="test",
        extra={"exe": "fake"},
    )


class _FakeClient:
    def __init__(self, solution_status: str = "Done"):
        self.solution_status = solution_status

    def verify_valid_connection(self):
        return True

    def wait_till_mechanical_is_ready(self, wait_time=0):
        return None

    def run_python_script(self, code):
        if (
            '"solution_status"' in code
            and '"solution_result_count"' in code
            and "result_file_available" in code
        ):
            return (
                '{"ok": true, "analyses": [{"index": 0, "type": "Static", '
                f'"solution_status": "{self.solution_status}", '
                '"solution_result_count": 1, "result_file_available": true}], '
                '"analysis_count": 1}'
            )
        if "solution_statuses" in code:
            return (
                '{"ok": true, "connected": true, '
                '"project_directory_known": true, "analysis_count": 1, '
                '"analysis_types": ["Static"], "active_analysis_index": 0, '
                f'"solution_statuses": ["{self.solution_status}"], '
                '"solution_result_counts": [1], '
                '"geometry_body_count": 1, "mesh_nodes": 10, '
                '"mesh_elements": 2, "result_file_available": false, '
                '"checkpoint_ready": true}'
            )
        if '"analyses"' in code:
            return (
                '{"ok": true, "connected": true, '
                '"analyses": [{"index": 0, "type": "Static", '
                '"child_count": 2, "solution_child_count": 1, '
                f'"solution_status": "{self.solution_status}", '
                '"solution_result_count": 1}], "analysis_count": 1, '
                '"named_selection_count": 0, "geometry_body_count": 1, '
                '"mesh": {"nodes": 10, "elements": 2}}'
            )
        if "analysis_count" in code:
            return '{"ok": true, "connected": true, "project_directory_known": true, "analysis_count": 1, "analysis_types": ["Static"], "active_analysis_index": 0, "geometry_body_count": 1, "mesh_nodes": 10, "mesh_elements": 2, "result_file_available": false, "checkpoint_ready": true}'
        if '"target": "mesh"' in code:
            return '{"ok": true, "target": "mesh", "nodes": 10, "elements": 2}'
        return "1"

    def run_python_script_from_file(self, path):
        return ""

    def get_product_info(self):
        return "Ansys Mechanical\nProduct Version:252\n"

    def exit(self):
        return None


def _install_fake_pm(monkeypatch, captured: list, raise_secure_transport: bool = False):
    """Replace _try_import_pymechanical with a stub that records launch kwargs."""
    import sim_plugin_mechanical.driver as drv

    class FakePM:
        __version__ = "0.12.6-fake"

        @staticmethod
        def launch_mechanical(**kwargs):
            captured.append(kwargs)
            if raise_secure_transport:
                raise RuntimeError(
                    "Mechanical version 252 does not support secure transport modes. "
                    "Update to Service Pack 3 or set transport_mode='insecure'."
                )
            return _FakeClient()

    monkeypatch.setattr(drv, "_try_import_pymechanical", lambda: FakePM)


class TestLaunchKwargs:
    """Tests for _build_launch_kwargs and run_file/launch wiring."""

    def test_run_file_uses_insecure_when_env_set(self, monkeypatch):
        captured: list[dict] = []
        d = MechanicalDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [_fake_install("25.2")])
        _install_fake_pm(monkeypatch, captured)
        monkeypatch.setenv("SIM_MECHANICAL_INSECURE_TRANSPORT", "1")

        result = d.run_file(FIXTURES / "mechanical_good.py")

        assert captured, "pm.launch_mechanical was never called"
        kw = captured[0]
        assert kw["transport_mode"] == "insecure"
        assert kw["batch"] is False  # run_file always GUI-visible by policy
        assert result.exit_code == 0

    def test_run_file_no_env_no_transport_override_on_252(self, monkeypatch):
        """Without the env var, 25.2 must NOT pass transport_mode (default secure)."""
        captured: list[dict] = []
        d = MechanicalDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [_fake_install("25.2")])
        _install_fake_pm(monkeypatch, captured)
        monkeypatch.delenv("SIM_MECHANICAL_INSECURE_TRANSPORT", raising=False)

        d.run_file(FIXTURES / "mechanical_good.py")

        assert "transport_mode" not in captured[0]

    def test_run_file_forces_insecure_for_pre_242(self, monkeypatch):
        """Ansys < 24.2 must always use insecure (no secure-gRPC support)."""
        captured: list[dict] = []
        d = MechanicalDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [_fake_install("24.1")])
        _install_fake_pm(monkeypatch, captured)
        monkeypatch.delenv("SIM_MECHANICAL_INSECURE_TRANSPORT", raising=False)

        d.run_file(FIXTURES / "mechanical_good.py")

        assert captured[0]["transport_mode"] == "insecure"

    def test_ui_mode_no_gui_maps_to_batch(self, monkeypatch):
        captured: list[dict] = []
        d = MechanicalDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [_fake_install("25.2")])
        _install_fake_pm(monkeypatch, captured)
        monkeypatch.setenv("SIM_MECHANICAL_INSECURE_TRANSPORT", "1")

        d.launch(ui_mode="no_gui")

        assert captured[0]["batch"] is True

    def test_ui_mode_batch_still_works(self, monkeypatch):
        """Backward-compat: existing callers passing 'batch' must keep working."""
        captured: list[dict] = []
        d = MechanicalDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [_fake_install("25.2")])
        _install_fake_pm(monkeypatch, captured)
        monkeypatch.setenv("SIM_MECHANICAL_INSECURE_TRANSPORT", "1")

        d.launch(ui_mode="batch")

        assert captured[0]["batch"] is True

    def test_ui_mode_gui_keeps_batch_false(self, monkeypatch):
        captured: list[dict] = []
        d = MechanicalDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [_fake_install("25.2")])
        _install_fake_pm(monkeypatch, captured)
        monkeypatch.setenv("SIM_MECHANICAL_INSECURE_TRANSPORT", "1")

        d.launch(ui_mode="gui")

        assert captured[0]["batch"] is False

    def test_session_summary_exposes_batch_policy(self, monkeypatch):
        captured: list[dict] = []
        d = MechanicalDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [_fake_install("25.2")])
        _install_fake_pm(monkeypatch, captured)
        monkeypatch.setenv("SIM_MECHANICAL_INSECURE_TRANSPORT", "1")

        d.launch(ui_mode="gui")
        summary = d.query("session.summary")

        assert summary["ui_mode"] == "gui"
        assert summary["batch"] is False
        assert summary["connected"] is True

    def test_session_health_connected_is_sanitized(self, monkeypatch):
        captured: list[dict] = []
        d = MechanicalDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [_fake_install("25.2")])
        _install_fake_pm(monkeypatch, captured)
        monkeypatch.setenv("SIM_MECHANICAL_INSECURE_TRANSPORT", "1")

        d.launch(ui_mode="gui")
        health = d.query("session.health")

        assert health["ok"] is True
        assert health["connected"] is True
        assert health["product_version"] == "252"
        assert "Enterprise" not in str(health)
        assert "license" not in str(health).lower()

    def test_ui_modes(self):
        d = MechanicalDriver()
        modes = d.query("ui.modes")
        assert modes["ok"] is True
        assert "gui" in modes["modes"]
        assert "no_gui" in modes["modes"]
        assert "batch" in modes["modes"]

    def test_project_identity_and_model_summary(self, monkeypatch):
        d = MechanicalDriver()
        d._client = _FakeClient()
        d._session_id = "s-test"
        d._ui_mode = "gui"
        d._batch = False

        identity = d.query("mechanical.project.identity")
        summary = d.query("mechanical.model.summary")
        props = d.query("mechanical.object.properties:mesh")

        assert identity["ok"] is True
        assert identity["analysis_count"] == 1
        assert identity["checkpoint_ready"] is True
        assert identity["solution_statuses"] == ["Done"]
        assert identity["solution_result_counts"] == [1]
        assert summary["analysis_count"] == 1
        assert summary["analyses"][0]["solution_status"] == "Done"
        assert summary["analyses"][0]["solution_result_count"] == 1
        assert summary["mesh"]["nodes"] == 10
        assert props["nodes"] == 10

    def test_solve_guard_marks_solve_required_as_failure(self):
        d = MechanicalDriver()
        d._client = _FakeClient(solution_status="SolveRequired")
        d._ui_mode = "no_gui"
        d._batch = True
        d.probes = []

        result = d.run("analysis.Solution.Solve(True)", label="solve")

        assert result["ok"] is False
        assert "SolveRequired" in result["error"]
        assert any(
            diag["code"] == "mechanical.solve.not_completed"
            for diag in result["diagnostics"]
        )

    def test_solve_guard_allows_done_status(self):
        d = MechanicalDriver()
        d._client = _FakeClient(solution_status="Done")
        d._ui_mode = "no_gui"
        d._batch = True
        d.probes = []

        result = d.run("analysis.Solution.Solve(True)", label="solve")

        assert result["ok"] is True
        assert not any(
            diag["code"] == "mechanical.solve.not_completed"
            for diag in result["diagnostics"]
        )

    def test_solve_guard_does_not_mark_setup_step(self):
        d = MechanicalDriver()
        d._client = _FakeClient(solution_status="SolveRequired")
        d._ui_mode = "no_gui"
        d._batch = True
        d.probes = []

        result = d.run("Model.AddStaticStructuralAnalysis()", label="setup")

        assert result["ok"] is True
        assert not any(
            diag["code"] == "mechanical.solve.not_completed"
            for diag in result["diagnostics"]
        )

    def test_health_degrades_when_verify_fails(self):
        class BadClient(_FakeClient):
            def verify_valid_connection(self):
                raise RuntimeError("connection failed")

        d = MechanicalDriver()
        d._client = BadClient()
        d._ui_mode = "gui"
        d._batch = False

        health = d.query("session.health")

        assert health["ok"] is False
        assert health["code"] == "mechanical.sdk.health_failed"

    def test_run_timeout_returns_structured_failure(self, monkeypatch):
        import time

        d = MechanicalDriver()
        d._client = _FakeClient()
        d._ui_mode = "gui"
        d._batch = False
        monkeypatch.setattr(d, "_dispatch", lambda code, label: time.sleep(0.2))

        result = d.run("slow()", timeout_s=0.01)

        assert result["ok"] is False
        assert "timeout_s" in result["error"]
        assert any(
            diag["code"] == "sim.runtime.snippet_timeout"
            for diag in result["diagnostics"]
        )

    def test_artifact_probe_detects_solver_files(self, tmp_path):
        from sim.inspect import InspectCtx
        from sim_plugin_mechanical.driver import MechanicalArtifactProbe

        (tmp_path / "file.rst").write_bytes(b"rst")
        (tmp_path / "file.err").write_text("solver warning", encoding="utf-8")
        (tmp_path / "solve.out").write_text("done", encoding="utf-8")

        probe = MechanicalArtifactProbe(only_new=True)
        ctx = InspectCtx(
            stdout="",
            stderr="",
            workdir=str(tmp_path),
            wall_time_s=0,
            exit_code=0,
            driver_name="mechanical",
            session_ns={},
            workdir_before=[],
        )

        result = probe.probe(ctx)
        codes = {d.code for d in result.diagnostics}
        assert "mechanical.result.rst_detected" in codes
        assert "mechanical.solve.err_detected" in codes
        assert "mechanical.solve.output_detected" in codes

    def test_launch_translates_secure_transport_error(self, monkeypatch):
        captured: list[dict] = []
        d = MechanicalDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [_fake_install("25.2")])
        _install_fake_pm(monkeypatch, captured, raise_secure_transport=True)
        monkeypatch.delenv("SIM_MECHANICAL_INSECURE_TRANSPORT", raising=False)

        with pytest.raises(RuntimeError) as exc_info:
            d.launch(ui_mode="gui")

        msg = str(exc_info.value)
        assert "SIM_MECHANICAL_INSECURE_TRANSPORT" in msg
        assert "secure transport" in msg.lower()


def _sim_cli_supports_target_pid() -> bool:
    """True iff this sim-cli build exposes target_pid on the GUI probes."""
    try:
        from sim.inspect import ScreenshotProbe
        return hasattr(ScreenshotProbe(), "target_pid")
    except Exception:
        return False


class TestProbePidPin:
    """Tests for the post-launch PID pinning of GUI probes.

    The pinning feature is only effective on sim-cli builds that expose
    ``target_pid`` on the GUI probes. Older builds silently fall back to
    substring matching — same behavior as v0.1.2.
    """

    @pytest.mark.skipif(
        not _sim_cli_supports_target_pid(),
        reason="installed sim-cli does not expose target_pid on GUI probes",
    )
    def test_launch_pins_target_pid_when_discovery_succeeds(self, monkeypatch):
        import sim_plugin_mechanical.driver as drv

        captured: list[dict] = []
        d = MechanicalDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [_fake_install("25.2")])
        _install_fake_pm(monkeypatch, captured)
        monkeypatch.setenv("SIM_MECHANICAL_INSECURE_TRANSPORT", "1")
        monkeypatch.setattr(drv, "_find_ansys_pid", lambda port=None, timeout_s=2.0: 4242)

        # Probes start unpinned.
        for p in d.probes:
            if hasattr(p, "target_pid"):
                assert p.target_pid is None

        d.launch(ui_mode="gui")

        # All probes that support target_pid are now pinned.
        pid_aware = [p for p in d.probes if hasattr(p, "target_pid")]
        assert pid_aware, "no probe in default set supports target_pid"
        for p in pid_aware:
            assert p.target_pid == 4242

    def test_launch_no_pid_falls_back_to_substring(self, monkeypatch):
        """When PID discovery fails, probes keep target_pid=None (substring fallback)."""
        import sim_plugin_mechanical.driver as drv

        captured: list[dict] = []
        d = MechanicalDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [_fake_install("25.2")])
        _install_fake_pm(monkeypatch, captured)
        monkeypatch.setenv("SIM_MECHANICAL_INSECURE_TRANSPORT", "1")
        monkeypatch.setattr(drv, "_find_ansys_pid", lambda port=None, timeout_s=2.0: None)

        d.launch(ui_mode="gui")

        for p in d.probes:
            if hasattr(p, "target_pid"):
                assert p.target_pid is None

    @pytest.mark.skipif(
        not _sim_cli_supports_target_pid(),
        reason="installed sim-cli does not expose target_pid on GUI probes",
    )
    def test_disconnect_clears_target_pid(self, monkeypatch):
        import sim_plugin_mechanical.driver as drv

        captured: list[dict] = []
        d = MechanicalDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [_fake_install("25.2")])
        _install_fake_pm(monkeypatch, captured)
        monkeypatch.setenv("SIM_MECHANICAL_INSECURE_TRANSPORT", "1")
        monkeypatch.setattr(drv, "_find_ansys_pid", lambda port=None, timeout_s=2.0: 4242)

        d.launch(ui_mode="gui")
        # Confirm pinned.
        pinned = [p.target_pid for p in d.probes if hasattr(p, "target_pid")]
        assert all(pid == 4242 for pid in pinned)

        d.disconnect()
        # Cleared after disconnect.
        for p in d.probes:
            if hasattr(p, "target_pid"):
                assert p.target_pid is None


class TestVersionCode:
    def test_version_code(self):
        from sim_plugin_mechanical.driver import _version_code
        assert _version_code("24.1") == 241
        assert _version_code("25.2") == 252


class TestExtractVersion:
    def test_extract(self):
        d = MechanicalDriver()
        assert d._extract_version(Path("v241")) == "24.1"
        assert d._extract_version(Path("v252")) == "25.2"
        assert d._extract_version(Path("not-a-version")) is None
