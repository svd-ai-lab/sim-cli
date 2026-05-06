"""Unit coverage for the HFSS plugin that does not require AEDT."""
from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from sim.driver import RunResult, SolverInstall

import sim_plugin_hfss.driver as drv
from sim_plugin_hfss import HfssDriver


FIXTURES = Path(__file__).parent.parent / "fixtures"


class TestDetect:
    def setup_method(self) -> None:
        self.driver = HfssDriver()

    def test_detect_modern_hfss_import(self) -> None:
        assert self.driver.detect(FIXTURES / "hfss_good.py") is True

    def test_detect_core_import_alias(self) -> None:
        assert self.driver.detect(FIXTURES / "hfss_core_import.py") is True

    def test_detect_legacy_pyaedt_import(self) -> None:
        assert self.driver.detect(FIXTURES / "hfss_legacy.py") is True

    def test_detect_unrelated_script(self) -> None:
        assert self.driver.detect(FIXTURES / "not_simulation.py") is False

    def test_detect_no_import(self) -> None:
        assert self.driver.detect(FIXTURES / "hfss_no_import.py") is False

    def test_detect_missing_file(self) -> None:
        assert self.driver.detect(Path("/does/not/exist.py")) is False

    def test_detect_syntax_error_still_detects(self) -> None:
        assert self.driver.detect(FIXTURES / "hfss_syntax_error.py") is True


class TestLint:
    def setup_method(self) -> None:
        self.driver = HfssDriver()

    def test_lint_good_script(self) -> None:
        result = self.driver.lint(FIXTURES / "hfss_good.py")
        assert result.ok is True

    def test_lint_syntax_error(self) -> None:
        result = self.driver.lint(FIXTURES / "hfss_syntax_error.py")
        assert result.ok is False
        assert any("syntax" in d.message for d in result.diagnostics)

    def test_lint_missing_import(self) -> None:
        result = self.driver.lint(FIXTURES / "hfss_no_import.py")
        assert result.ok is False
        assert any("HFSS" in d.message for d in result.diagnostics)

    def test_lint_missing_file(self, tmp_path: Path) -> None:
        result = self.driver.lint(tmp_path / "missing.py")
        assert result.ok is False
        assert result.diagnostics[0].level == "error"

    def test_lint_rejects_direct_aedt_file(self, tmp_path: Path) -> None:
        model = tmp_path / "model.aedt"
        model.write_text("", encoding="utf-8")
        result = self.driver.lint(model)
        assert result.ok is False
        assert "Python scripts" in result.diagnostics[0].message


class TestInstallDiscovery:
    def test_env_install_discovery(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        exe = tmp_path / "v261" / "Win64" / "ansysedt.exe"
        exe.parent.mkdir(parents=True)
        exe.write_text("", encoding="utf-8")
        monkeypatch.setenv("SIM_HFSS_AEDT_ROOT", str(exe.parent))
        monkeypatch.setattr(drv, "_INSTALL_FINDERS", [drv._candidates_from_env])

        installs = HfssDriver().detect_installed()

        assert len(installs) == 1
        assert installs[0].version == "2026.1"
        assert installs[0].extra["executable"] == str(exe)

    def test_ansysem_env_version(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        exe = tmp_path / "AnsysEM" / "Win64" / "ansysedt.exe"
        exe.parent.mkdir(parents=True)
        exe.write_text("", encoding="utf-8")
        monkeypatch.setenv("ANSYSEM_ROOT252", str(exe.parent))
        monkeypatch.setattr(drv, "_INSTALL_FINDERS", [drv._candidates_from_env])

        installs = HfssDriver().detect_installed()

        assert installs[0].version == "2025.2"
        assert installs[0].source == "env:ANSYSEM_ROOT252"

    def test_ansysemsv_env_marks_student(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        exe = tmp_path / "AnsysEM" / "ansysedtsv.exe"
        exe.parent.mkdir(parents=True)
        exe.write_text("", encoding="utf-8")
        monkeypatch.setenv("ANSYSEMSV_ROOT252", str(exe.parent))
        monkeypatch.setattr(drv, "_INSTALL_FINDERS", [drv._candidates_from_env])

        installs = HfssDriver().detect_installed()

        assert installs[0].version == "2025.2"
        assert installs[0].source == "env:ANSYSEMSV_ROOT252"
        assert installs[0].extra["student_version"] is True

    def test_ansysem_env_names_are_case_insensitive(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        exe = tmp_path / "AnsysEM" / "ansysedt.exe"
        exe.parent.mkdir(parents=True)
        exe.write_text("", encoding="utf-8")
        monkeypatch.setenv("ansysem_root252", str(exe.parent))
        monkeypatch.setattr(drv, "_INSTALL_FINDERS", [drv._candidates_from_env])

        installs = HfssDriver().detect_installed()

        assert installs[0].version == "2025.2"
        assert installs[0].extra["student_version"] is False

    def test_student_root_discovery(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        exe = tmp_path / "ANSYS Inc" / "ANSYS Student" / "v252" / "AnsysEM" / "ansysedtsv.exe"
        exe.parent.mkdir(parents=True)
        exe.write_text("", encoding="utf-8")
        monkeypatch.setattr(
            drv,
            "_DEFAULT_INSTALL_PATTERNS",
            [str(tmp_path / "ANSYS Inc" / "ANSYS Student" / "v*")],
        )
        monkeypatch.setattr(drv, "_INSTALL_FINDERS", [drv._candidates_from_defaults])

        installs = HfssDriver().detect_installed()

        assert len(installs) == 1
        assert installs[0].version == "2025.2"
        assert installs[0].extra["executable"] == str(exe)
        assert installs[0].extra["student_version"] is True

    def test_path_discovery_checks_student_launcher(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        exe = tmp_path / "AnsysEM" / "ansysedtsv.exe"
        exe.parent.mkdir(parents=True)
        exe.write_text("", encoding="utf-8")

        def fake_which(name: str) -> str | None:
            return str(exe) if name == "ansysedtsv.exe" else None

        monkeypatch.setattr(drv.shutil, "which", fake_which)
        monkeypatch.setattr(drv, "_INSTALL_FINDERS", [drv._candidates_from_path])

        installs = HfssDriver().detect_installed()

        assert len(installs) == 1
        assert installs[0].source == "which:ansysedtsv.exe"
        assert installs[0].extra["student_version"] is True

    def test_prepare_pyaedt_environment_uses_student_env_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ANSYSEMSV_ROOT252", raising=False)

        prepared = drv._prepare_pyaedt_environment(_student_install())

        assert prepared == {
            "ANSYSEMSV_ROOT252": "C:/Program Files/ANSYS Inc/ANSYS Student/v252/AnsysEM"
        }
        assert drv.os.environ["ANSYSEMSV_ROOT252"].endswith("/AnsysEM")


class TestConnect:
    def test_connect_not_installed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        driver = HfssDriver()
        monkeypatch.setattr(driver, "detect_installed", lambda: [])

        info = driver.connect()

        assert info.status == "not_installed"
        assert "SIM_HFSS_AEDT_ROOT" in info.message

    def test_connect_pyaedt_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        driver = HfssDriver()
        monkeypatch.delenv("ANSYSEM_ROOT261", raising=False)
        monkeypatch.setattr(driver, "detect_installed", lambda: [_install()])
        monkeypatch.setattr(drv, "_try_import_pyaedt", lambda: None)

        info = driver.connect()

        assert info.status == "error"
        assert "PyAEDT" in info.message

    def test_connect_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        driver = HfssDriver()
        monkeypatch.delenv("ANSYSEM_ROOT261", raising=False)
        monkeypatch.setattr(driver, "detect_installed", lambda: [_install()])
        monkeypatch.setattr(
            drv,
            "_try_import_pyaedt",
            lambda: drv._PyaedtApi(Desktop=None, Hfss=FakeHfss, version="0.26.3"),
        )

        info = driver.connect()

        assert info.status == "ok"
        assert info.solver_version == "2026.1"


class TestParseOutput:
    def setup_method(self) -> None:
        self.driver = HfssDriver()

    def test_last_json_line(self) -> None:
        assert self.driver.parse_output('log\n{"s11_db": -18.2}\n') == {"s11_db": -18.2}

    def test_invalid_json_is_skipped(self) -> None:
        assert self.driver.parse_output("{broken\n{\"ok\": true}\n") == {"ok": True}

    def test_no_json(self) -> None:
        assert self.driver.parse_output("plain log") == {}


class TestRunFile:
    def test_run_file_uses_current_python(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        def fake_run(command, *, script, solver):
            captured["command"] = command
            captured["script"] = script
            captured["solver"] = solver
            return RunResult(
                exit_code=0,
                stdout="",
                stderr="",
                duration_s=0.0,
                script=str(script),
                solver=solver,
                timestamp="t",
            )

        monkeypatch.setattr(drv, "run_subprocess", fake_run)

        result = HfssDriver().run_file(FIXTURES / "hfss_good.py")

        assert result.ok is True
        assert captured["command"][0]
        assert captured["solver"] == "hfss"

    def test_run_file_rejects_aedt_file(self, tmp_path: Path) -> None:
        with pytest.raises(RuntimeError, match="Direct .aedt"):
            HfssDriver().run_file(tmp_path / "model.aedt")


class TestSession:
    def test_launch_run_query_disconnect(self, monkeypatch: pytest.MonkeyPatch) -> None:
        driver = HfssDriver()
        monkeypatch.delenv("ANSYSEM_ROOT261", raising=False)
        monkeypatch.setattr(driver, "detect_installed", lambda: [_install()])
        monkeypatch.setattr(
            drv,
            "_try_import_pyaedt",
            lambda: drv._PyaedtApi(Desktop=None, Hfss=FakeHfss, version="0.26.3"),
        )

        launched = driver.launch(ui_mode="no_gui", project="demo.aedt", design="HFSSDesign1")

        assert launched["ok"] is True
        assert FakeHfss.last_kwargs["non_graphical"] is True
        assert FakeHfss.last_kwargs["student_version"] is False
        assert FakeHfss.last_kwargs["project"] == "demo.aedt"

        run = driver.run('hfss.marker = "changed"\n{"marker": hfss.marker}', label="mutate")
        assert run["ok"] is True
        assert run["result"] == {"marker": "changed"}

        summary = driver.query("session.summary")
        assert summary["connected"] is True
        assert summary["run_count"] == 1

        identity = driver.query("hfss.project.identity")
        assert identity["project_name"] == "DemoProject"

        design = driver.query("hfss.design.summary")
        assert design["design_name"] == "HFSSDesign1"
        assert design["setup_names"] == ["Setup1"]

        last = driver.query("last.result")
        assert last["result"]["label"] == "mutate"

        disconnected = driver.disconnect()
        assert disconnected == {"ok": True, "disconnected": True}
        assert FakeHfss.release_calls

    def test_launch_without_install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        driver = HfssDriver()
        monkeypatch.setattr(driver, "detect_installed", lambda: [])

        result = driver.launch()

        assert result["ok"] is False
        assert result["error_code"] == "SOLVER_NOT_INSTALLED"

    def test_launch_infers_student_version_from_install_metadata(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        driver = HfssDriver()
        monkeypatch.delenv("ANSYSEMSV_ROOT252", raising=False)
        monkeypatch.setattr(driver, "detect_installed", lambda: [_student_install()])
        monkeypatch.setattr(
            drv,
            "_try_import_pyaedt",
            lambda: drv._PyaedtApi(Desktop=None, Hfss=FakeHfss, version="0.26.3"),
        )

        launched = driver.launch(ui_mode="gui")

        assert launched["ok"] is True
        assert launched["student_version"] is True
        assert FakeHfss.last_kwargs["student_version"] is True
        assert launched["launch_options"]["prepared_env"] == {
            "ANSYSEMSV_ROOT252": "C:/Program Files/ANSYS Inc/ANSYS Student/v252/AnsysEM"
        }

    def test_launch_respects_explicit_student_version_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        driver = HfssDriver()
        monkeypatch.delenv("ANSYSEMSV_ROOT252", raising=False)
        monkeypatch.setattr(driver, "detect_installed", lambda: [_student_install()])
        monkeypatch.setattr(
            drv,
            "_try_import_pyaedt",
            lambda: drv._PyaedtApi(Desktop=None, Hfss=FakeHfss, version="0.26.3"),
        )

        launched = driver.launch(student_version=False)

        assert launched["ok"] is True
        assert FakeHfss.last_kwargs["student_version"] is False

    def test_run_without_session(self) -> None:
        result = HfssDriver().run("1 + 1")
        assert result["ok"] is False
        assert result["error_code"] == "SESSION_NOT_FOUND"


def _install() -> SolverInstall:
    return SolverInstall(
        name="hfss",
        version="2026.1",
        path="/opt/AnsysEM/v261/Linux64",
        source="test",
        extra={"executable": "/opt/AnsysEM/v261/Linux64/ansysedt", "student_version": False},
    )


def _student_install() -> SolverInstall:
    return SolverInstall(
        name="hfss",
        version="2025.2",
        path="C:/Program Files/ANSYS Inc/ANSYS Student/v252/AnsysEM",
        source="test",
        extra={
            "executable": "C:/Program Files/ANSYS Inc/ANSYS Student/v252/AnsysEM/ansysedtsv.exe",
            "student_version": True,
        },
    )


class FakeHfss:
    last_kwargs: dict[str, object] = {}
    release_calls: list[dict[str, object]] = []

    def __init__(self, **kwargs: object) -> None:
        type(self).last_kwargs = kwargs
        type(self).release_calls = []
        self.project_name = "DemoProject"
        self.project_file = "demo.aedt"
        self.project_path = "/tmp/demo"
        self.working_directory = "/tmp/demo"
        self.aedt_version_id = "2026.1"
        self.design_name = "HFSSDesign1"
        self.design_type = "HFSS"
        self.solution_type = "Modal"
        self.setup_names = ["Setup1"]
        self.excitation_names = ["Port1"]
        self.valid_design = True
        self.desktop_class = SimpleNamespace()

    def release_desktop(self, **kwargs: object) -> None:
        type(self).release_calls.append(kwargs)
