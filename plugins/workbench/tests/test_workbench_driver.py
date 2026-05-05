"""Tier 1 + Tier 2 tests for the Ansys Workbench driver.

Tests run without a real Workbench installation — detection is monkeypatched.
Tier 4 (real solver) tests are in test_workbench_integration.py.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sim.driver import DriverProtocol, SolverInstall

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _fake_install(tmp_path: Path, version: str = "24.1") -> SolverInstall:
    version_dir = "v" + version.replace(".", "")
    root = tmp_path / "ANSYS Inc" / version_dir
    runwb2 = root / "Framework" / "bin" / "Win64" / "RunWB2.exe"
    runwb2.parent.mkdir(parents=True)
    runwb2.write_text("", encoding="utf-8")
    return SolverInstall(
        name="workbench",
        version=version,
        path=str(root),
        source=f"test:{version_dir}",
    )


@pytest.fixture
def driver():
    from sim_plugin_workbench import WorkbenchDriver
    return WorkbenchDriver()


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------

class TestProtocolCompliance:
    def test_is_protocol(self, driver):
        assert isinstance(driver, DriverProtocol)

    def test_name(self, driver):
        assert driver.name == "workbench"


# ---------------------------------------------------------------------------
# detect()
# ---------------------------------------------------------------------------

class TestDetect:
    def test_detect_wbjn_good(self, driver):
        assert driver.detect(FIXTURES / "workbench_good.wbjn") is True

    def test_detect_wbjn_no_marker(self, driver):
        assert driver.detect(FIXTURES / "workbench_no_marker.wbjn") is True

    def test_detect_py_with_wb_import(self, driver):
        assert driver.detect(FIXTURES / "workbench_py_good.py") is True

    def test_detect_unrelated_py(self, driver):
        # A plain .py without `import ansys.workbench` must not be claimed.
        assert driver.detect(FIXTURES / "non_workbench_py.py") is False

    def test_detect_missing_file(self, driver):
        assert driver.detect(FIXTURES / "nonexistent.wbjn") is False

    def test_detect_non_workbench_py(self, driver):
        # Sanity: same fixture as test_detect_unrelated_py — kept as a
        # second guard so future cross-driver fixtures don't accidentally
        # be misclassified by this driver.
        assert driver.detect(FIXTURES / "non_workbench_py.py") is False


# ---------------------------------------------------------------------------
# lint()
# ---------------------------------------------------------------------------

class TestLint:
    def test_lint_good_wbjn(self, driver):
        result = driver.lint(FIXTURES / "workbench_good.wbjn")
        assert result.ok is True

    def test_lint_bad_syntax(self, driver):
        result = driver.lint(FIXTURES / "workbench_bad_syntax.wbjn")
        assert result.ok is False
        assert any(d.level == "error" for d in result.diagnostics)

    def test_lint_no_marker(self, driver):
        result = driver.lint(FIXTURES / "workbench_no_marker.wbjn")
        assert result.ok is True
        assert any(d.level == "warning" for d in result.diagnostics)

    def test_lint_py_good(self, driver):
        result = driver.lint(FIXTURES / "workbench_py_good.py")
        assert result.ok is True


# ---------------------------------------------------------------------------
# connect()
# ---------------------------------------------------------------------------

class TestConnect:
    def test_connect_not_installed(self, driver, monkeypatch):
        monkeypatch.setattr(driver, "detect_installed", lambda: [])
        info = driver.connect()
        assert info.status == "not_installed"

    def test_connect_found(self, driver, monkeypatch):
        fake = [SolverInstall(
            name="workbench", version="24.1",
            path="C:/fake/ansys/v241", source="env:AWP_ROOT241",
        )]
        monkeypatch.setattr(driver, "detect_installed", lambda: fake)
        info = driver.connect()
        assert info.status == "ok"
        assert info.version == "24.1"

    def test_connect_message_shows_sdk_status(self, driver, monkeypatch):
        """Message should indicate whether SDK is available."""
        fake = [SolverInstall(
            name="workbench", version="24.1",
            path="C:/fake/v241", source="env:AWP_ROOT241",
        )]
        monkeypatch.setattr(driver, "detect_installed", lambda: fake)
        info = driver.connect()
        # Should mention either PyWorkbench version or RunWB2 fallback
        assert "PyWorkbench" in info.message or "RunWB2" in info.message


# ---------------------------------------------------------------------------
# parse_output()
# ---------------------------------------------------------------------------

class TestParseOutput:
    def test_last_json_line(self, driver):
        stdout = 'some log\n{"status": "done", "elapsed": 12.3}\ntrailer'
        assert driver.parse_output(stdout) == {"status": "done", "elapsed": 12.3}

    def test_no_json(self, driver):
        assert driver.parse_output("no json here\n") == {}

    def test_empty(self, driver):
        assert driver.parse_output("") == {}


# ---------------------------------------------------------------------------
# detect_installed()
# ---------------------------------------------------------------------------

class TestDetectInstalled:
    def test_returns_list(self, driver):
        assert isinstance(driver.detect_installed(), list)

    def test_env_var_detection(self, driver, monkeypatch, tmp_path):
        fake = _fake_install(tmp_path)
        monkeypatch.setenv("AWP_ROOT241", fake.path)
        result = driver.detect_installed()
        env_sources = [i for i in result if i.source.startswith("env:")]
        assert len(env_sources) >= 1
        assert any(i.version == "24.1" and i.path == fake.path for i in env_sources)

    def test_version_extraction(self, driver):
        assert driver._extract_version(Path("v241")) == "24.1"
        assert driver._extract_version(Path("v251")) == "25.1"
        assert driver._extract_version(Path("v232")) == "23.2"
        assert driver._extract_version(Path("some_random")) is None


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

class TestSessionLifecycle:
    def test_not_connected_initially(self, driver):
        assert driver.is_connected is False

    def test_disconnect_noop_when_not_connected(self, driver):
        driver.disconnect()
        assert driver.is_connected is False

    def test_run_raises_without_session(self, driver):
        result = driver.run("print('hello')")
        assert result["ok"] is False
        assert "No active session" in result["error"]

    def test_query_raises_unknown(self, driver):
        with pytest.raises(ValueError, match="unknown query"):
            driver.query("nonexistent")

    def test_health_disconnected(self, driver):
        health = driver.query("session.health")
        assert health["ok"] is False
        assert health["connected"] is False
        assert health["code"] == "workbench.session.disconnected"
        assert "license" not in str(health).lower()

    def test_ui_modes(self, driver):
        modes = driver.query("ui.modes")
        assert modes["ok"] is True
        assert "gui" in modes["modes"]
        assert "no_gui" in modes["modes"]
        assert "batch-fallback" in modes["modes"]

    def test_templates_visible_requires_session(self, driver):
        result = driver.query("workbench.templates.visible")
        assert result["ok"] is False
        assert result["code"] == "workbench.session.disconnected"

    def test_templates_visible_query_uses_live_journal(self, driver, monkeypatch):
        driver._backend = "pyworkbench"
        driver._client = object()
        captured = {}

        def fake_dispatch(code, label):
            captured["code"] = code
            return {
                "ok": True,
                "stdout": '{"ok": true, "count": 1, "templates": [{"name": "FLUENT"}]}',
                "error": None,
                "result": {"ok": True, "count": 1, "templates": [{"name": "FLUENT"}]},
            }

        monkeypatch.setattr(driver, "_dispatch", fake_dispatch)
        result = driver.query("workbench.templates.visible")

        assert result["ok"] is True
        assert result["templates"][0]["name"] == "FLUENT"
        assert "GetAllVisibleTemplates" in captured["code"]

    def test_templates_resolve_query_builds_dynamic_probe(self, driver, monkeypatch):
        driver._backend = "pyworkbench"
        driver._client = object()
        captured = {}

        def fake_dispatch(code, label):
            captured["code"] = code
            return {
                "ok": True,
                "stdout": '{"ok": true, "template": {"name": "Static Structural (ANSYS)", "solver": null}}',
                "error": None,
                "result": {
                    "ok": True,
                    "template": {"name": "Static Structural (ANSYS)", "solver": None},
                },
            }

        monkeypatch.setattr(driver, "_dispatch", fake_dispatch)
        result = driver.query("workbench.templates.resolve:Static Structural")

        assert result["ok"] is True
        assert result["template"]["name"] == "Static Structural (ANSYS)"
        assert "Static Structural" in captured["code"]
        assert "GetTemplate" in captured["code"]


# ---------------------------------------------------------------------------
# Fallback logic
# ---------------------------------------------------------------------------

class TestFallback:
    """SDK failure should fall back to RunWB2."""

    def test_run_file_falls_back_when_sdk_import_fails(self, driver, monkeypatch, tmp_path):
        """If ansys.workbench.core can't be imported, fall back to RunWB2."""
        monkeypatch.setattr(
            "sim_plugin_workbench.driver._try_import_pyworkbench", lambda: None
        )
        monkeypatch.setattr(driver, "detect_installed", lambda: [_fake_install(tmp_path)])
        monkeypatch.setattr(
            "sim_plugin_workbench.driver.subprocess.run",
            lambda *args, **kwargs: SimpleNamespace(
                returncode=0,
                stdout="Framework error caught\n",
                stderr="",
            ),
        )
        # Fallback to RunWB2 should produce a RunResult with captured output.
        # workbench_good.wbjn has a known API error (GetModel not available),
        # so it should report as failed with errors captured.
        result = driver.run_file(FIXTURES / "workbench_good.wbjn")
        assert result.solver == "workbench"
        # The script has errors — verify the driver actually detected them
        assert not result.ok, f"Expected failure but got ok=True. stdout={result.stdout[:200]}, errors={result.errors}"

    def test_launch_falls_back_when_sdk_raises(self, driver, monkeypatch, tmp_path):
        """If SDK launch raises, fall back to RunWB2 session."""
        def _mock_pywb():
            class _FakeModule:
                __version__ = "0.0.0"
                @staticmethod
                def launch_workbench(**kwargs):
                    raise RuntimeError("SDK launch failed")
            return _FakeModule()

        monkeypatch.setattr(
            "sim_plugin_workbench.driver._try_import_pyworkbench", _mock_pywb
        )
        monkeypatch.setattr(driver, "detect_installed", lambda: [_fake_install(tmp_path)])
        info = driver.launch(mode="workbench")
        assert info["ok"] is True
        assert info["backend"] == "runwb2"
        assert driver.query("session.health")["code"] == "workbench.session.fallback_ready"
        driver.disconnect()

    def test_launch_enables_gui_probes_for_visible_ui(self, driver, monkeypatch, tmp_path):
        def _mock_pywb():
            class _Client:
                def is_alive(self):
                    return True

                def run_script_string(self, code, log_level="warning"):
                    return '{"ok": true}'

                def exit(self):
                    return None

            class _FakeModule:
                __version__ = "0.0.0"

                @staticmethod
                def launch_workbench(**kwargs):
                    return _Client()

            return _FakeModule()

        monkeypatch.setattr(
            "sim_plugin_workbench.driver._try_import_pyworkbench", _mock_pywb
        )
        monkeypatch.setattr(driver, "detect_installed", lambda: [_fake_install(tmp_path)])

        info = driver.launch(mode="workbench", ui_mode="gui")

        assert info["backend"] == "pyworkbench"
        assert any(getattr(p, "name", "") == "gui-dialog" for p in driver.probes)
        health = driver.query("session.health")
        assert health["ok"] is True
        assert health["ui_capabilities"]["screenshot_expected"] is True
        driver.disconnect()

    def test_launch_keeps_gui_probes_off_for_no_gui(self, driver, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "sim_plugin_workbench.driver._try_import_pyworkbench", lambda: None
        )
        monkeypatch.setattr(driver, "detect_installed", lambda: [_fake_install(tmp_path)])

        driver.launch(mode="workbench", ui_mode="no_gui")

        assert not any(getattr(p, "name", "") == "gui-dialog" for p in driver.probes)
        driver.disconnect()

    def test_systems_summary_from_last_result(self, driver):
        driver._backend = "pyworkbench"
        driver._client = object()
        driver._last_run = {
            "result": {
                "ok": True,
                "component_count": 6,
                "components": [
                    "Engineering Data", "Geometry", "Model",
                    "Setup", "Solution", "Results",
                ],
                "project_file": "example.wbpj",
            }
        }

        summary = driver.query("workbench.systems.summary")
        identity = driver.query("workbench.project.identity")

        assert summary["system_count"] == 1
        assert summary["systems"][0]["type"] == "Static Structural"
        assert identity["checkpoint_ready"] is True
        assert identity["project_file_name"] == "example.wbpj"

    def test_run_timeout_returns_structured_failure(self, driver, monkeypatch):
        import time

        driver._backend = "pyworkbench"
        driver._client = object()
        monkeypatch.setattr(driver, "_dispatch", lambda code, label: time.sleep(0.2))

        result = driver.run("slow()", timeout_s=0.01)

        assert result["ok"] is False
        assert "timeout_s" in result["error"]
        assert any(
            d["code"] == "sim.runtime.snippet_timeout"
            for d in result["diagnostics"]
        )

    def test_run_marks_parsed_journal_failure(self, driver, monkeypatch):
        driver._backend = "pyworkbench"
        driver._client = object()
        monkeypatch.setattr(
            driver,
            "_dispatch",
            lambda code, label: {
                "ok": True,
                "label": label,
                "stdout": '{"ok": false, "error": "template missing"}',
                "stderr": "",
                "error": None,
                "result": {"ok": False, "error": "template missing"},
                "elapsed_s": 0.01,
            },
        )

        result = driver.run("bad journal", label="template-probe")

        assert result["ok"] is False
        assert result["error"] == "template missing"
        assert any(
            d["code"] == "workbench.journal.result_failed"
            for d in result["diagnostics"]
        )

    def test_run_keeps_parsed_journal_success(self, driver, monkeypatch):
        driver._backend = "pyworkbench"
        driver._client = object()
        monkeypatch.setattr(
            driver,
            "_dispatch",
            lambda code, label: {
                "ok": True,
                "label": label,
                "stdout": '{"ok": true}',
                "stderr": "",
                "error": None,
                "result": {"ok": True},
                "elapsed_s": 0.01,
            },
        )

        result = driver.run("good journal", label="template-probe")

        assert result["ok"] is True
        assert not any(
            d["code"] == "workbench.journal.result_failed"
            for d in result["diagnostics"]
        )


# ---------------------------------------------------------------------------
# run_file()
# ---------------------------------------------------------------------------

class TestRunFile:
    def test_raises_when_not_installed(self, driver, monkeypatch):
        monkeypatch.setattr(driver, "detect_installed", lambda: [])
        with pytest.raises(RuntimeError, match="not found"):
            driver.run_file(FIXTURES / "workbench_good.wbjn")
