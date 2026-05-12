from __future__ import annotations

import json
from pathlib import Path

import pytest

from sim.driver import SolverInstall
from sim_plugin_hypermesh import HyperMeshDriver
from sim_plugin_hypermesh import driver as driver_mod


class FakeProcess:
    def __init__(self, pid: int = 1234, returncode=None):
        self.pid = pid
        self.returncode = returncode
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode


class FakeGui:
    def __init__(self, windows=None):
        self.windows = windows or [{
            "hwnd": 100,
            "pid": 1234,
            "proc": "hwx.exe",
            "title": "HyperMesh",
            "rect": [0, 0, 100, 100],
        }]

    def list_windows(self):
        return {"ok": True, "windows": list(self.windows)}


def _install(tmp_path: Path) -> SolverInstall:
    exe = tmp_path / "runhwx.exe"
    exe.write_text("placeholder", encoding="utf-8")
    return SolverInstall(
        name="hypermesh",
        version="2026",
        path=str(tmp_path),
        source="test",
        extra={"runhwx": str(exe), "raw_version": "2026"},
    )


def _launched_driver(monkeypatch, tmp_path: Path) -> HyperMeshDriver:
    driver = HyperMeshDriver()
    monkeypatch.setattr(driver, "_resolve_install", lambda **_kwargs: _install(tmp_path))
    monkeypatch.setattr(driver, "_start_gui_process", lambda *_args, **_kwargs: FakeProcess())
    driver.launch(workspace=str(tmp_path), ui_mode="gui")
    driver._gui = FakeGui()
    return driver


class TestDetectAndLint:
    def test_detect_missing_file_is_false(self, tmp_path):
        assert HyperMeshDriver().detect(tmp_path / "missing.py") is False

    def test_detect_import(self, tmp_path):
        script = tmp_path / "case.py"
        script.write_text("import hm\nmodel = hm.Model()\n", encoding="utf-8")
        assert HyperMeshDriver().detect(script) is True

    def test_lint_missing_file_is_diagnostic(self, tmp_path):
        result = HyperMeshDriver().lint(tmp_path / "missing.py")
        assert result.ok is False
        assert result.diagnostics[0].level == "error"

    def test_lint_no_import_is_warning_not_blocker(self, tmp_path):
        script = tmp_path / "step.py"
        script.write_text("_result = {'ok': True}\n", encoding="utf-8")
        result = HyperMeshDriver().lint(script)
        assert result.ok is True
        assert any(item.level == "warning" for item in result.diagnostics)


class TestDiscovery:
    def test_detect_installed_uses_finder_chain(self, monkeypatch, tmp_path):
        root = tmp_path / "Altair" / "2026"
        exe = root / "hwdesktop" / "hwx" / "bin" / "win64" / "runhwx.exe"
        exe.parent.mkdir(parents=True)
        exe.write_text("placeholder", encoding="utf-8")

        monkeypatch.setattr(
            driver_mod,
            "_INSTALL_FINDERS",
            [lambda: [(root, "test")]],
        )

        installs = HyperMeshDriver().detect_installed()
        assert len(installs) == 1
        assert installs[0].version == "2026"
        assert installs[0].extra["runhwx"].endswith("runhwx.exe")

    def test_connect_reports_not_installed(self, monkeypatch):
        monkeypatch.setattr(driver_mod, "_scan_installs", lambda: [])
        info = HyperMeshDriver().connect()
        assert info.status == "not_installed"


class TestLaunchAndHealth:
    def test_rejects_no_gui(self):
        with pytest.raises(RuntimeError, match="ui_mode=gui"):
            HyperMeshDriver().launch(ui_mode="no_gui")

    def test_launch_gui_sets_session_and_gui_tool(self, monkeypatch, tmp_path):
        driver = _launched_driver(monkeypatch, tmp_path)

        health = driver.health()

        assert driver.supports_session is True
        assert health["connected"] is True
        assert health["ui_capabilities"]["model_builder_live"] is True
        assert driver._gui is not None

    def test_disconnect_is_idempotent_and_preserves_process_by_default(
        self, monkeypatch, tmp_path
    ):
        driver = _launched_driver(monkeypatch, tmp_path)
        proc = driver._proc

        first = driver.disconnect()
        second = driver.disconnect()

        assert first["ok"] is True
        assert second["ok"] is True
        assert proc.terminated is False

    def test_disconnect_can_close_process(self, monkeypatch, tmp_path):
        driver = HyperMeshDriver()
        monkeypatch.setattr(driver, "_resolve_install", lambda **_kwargs: _install(tmp_path))
        monkeypatch.setattr(driver, "_start_gui_process", lambda *_args, **_kwargs: FakeProcess())
        driver.launch(workspace=str(tmp_path), ui_mode="gui", close_on_disconnect=True)
        proc = driver._proc

        driver.disconnect()

        assert proc.terminated is True


class TestRun:
    def test_run_success_reads_result_file(self, monkeypatch, tmp_path):
        driver = _launched_driver(monkeypatch, tmp_path)

        def submit(script_path, log_path):
            result_path = driver._paths.results / f"{script_path.stem}.json"
            result_path.write_text(
                json.dumps({
                    "ok": True,
                    "stdout": "hello\n",
                    "stderr": "",
                    "result": {"nodes": 10},
                }),
                encoding="utf-8",
            )
            log_path.write_text("submitted", encoding="utf-8")
            return FakeProcess(pid=2222, returncode=0)

        monkeypatch.setattr(driver, "_submit_script", submit)

        result = driver.run("_result = {'nodes': 10}", label="smoke", timeout_s=1)

        assert result["ok"] is True
        assert result["label"] == "smoke"
        assert result["result"] == {"nodes": 10}
        assert result["stdout"] == "hello\n"
        assert Path(result["script_path"]).is_file()

    def test_run_failure_from_payload(self, monkeypatch, tmp_path):
        driver = _launched_driver(monkeypatch, tmp_path)

        def submit(script_path, log_path):
            result_path = driver._paths.results / f"{script_path.stem}.json"
            result_path.write_text(
                json.dumps({
                    "ok": False,
                    "stdout": "",
                    "stderr": "bad",
                    "error": "failed",
                    "result": None,
                }),
                encoding="utf-8",
            )
            return FakeProcess(pid=2222, returncode=0)

        monkeypatch.setattr(driver, "_submit_script", submit)

        result = driver.run("raise RuntimeError('failed')", timeout_s=1)

        assert result["ok"] is False
        assert result["error"] == "failed"
        assert result["diagnostics"][0]["code"] == "hypermesh.script.failed"

    def test_run_timeout(self, monkeypatch, tmp_path):
        driver = _launched_driver(monkeypatch, tmp_path)
        monkeypatch.setattr(
            driver,
            "_submit_script",
            lambda *_args, **_kwargs: FakeProcess(pid=2222, returncode=None),
        )

        result = driver.run("_result = None", timeout_s=0.01)

        assert result["ok"] is False
        assert result["error_code"] == "hypermesh.script.timeout"

    def test_run_disconnected(self):
        result = HyperMeshDriver().run("_result = True")

        assert result["ok"] is False
        assert result["error_code"] == "hypermesh.session.disconnected"

    def test_manual_submission_mode_writes_script(self, monkeypatch, tmp_path):
        driver = HyperMeshDriver()
        monkeypatch.setattr(driver, "_resolve_install", lambda **_kwargs: _install(tmp_path))
        monkeypatch.setattr(driver, "_start_gui_process", lambda *_args, **_kwargs: FakeProcess())
        driver.launch(workspace=str(tmp_path), ui_mode="gui", script_submit="manual")

        result = driver.run("_result = {'ok': True}")

        assert result["ok"] is False
        assert result["error_code"] == "hypermesh.script.manual_submission"
        assert Path(result["script_path"]).is_file()


class TestQueries:
    def test_query_targets(self, monkeypatch, tmp_path):
        driver = _launched_driver(monkeypatch, tmp_path)
        (tmp_path / "mesh.fem").write_text("mesh", encoding="utf-8")

        assert driver.query("session.health")["ok"] is True
        assert driver.query("ui.modes")["default"] == "gui"
        assert driver.query("hypermesh.session.identity")["ok"] is True
        files = driver.query("hypermesh.workspace.files")["files"]
        assert any(item["path"] == "mesh.fem" for item in files)

    def test_unknown_query(self):
        result = HyperMeshDriver().query("unknown")
        assert result["ok"] is False
