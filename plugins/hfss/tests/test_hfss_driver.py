"""Unit coverage for the HFSS plugin that does not require AEDT."""
from __future__ import annotations

import subprocess
import time
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
        monkeypatch.delenv("ANSYSEMSV_ROOT252", raising=False)
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


class TestTouchstoneSummary:
    @pytest.mark.parametrize(
        ("header", "rows", "expected_min_db"),
        [
            ("# GHz S MA R 50", ["5.0 0.5 0", "5.1 0.1 0"], -20.0),
            ("# GHz S DB R 50", ["5.0 -3 0", "5.1 -12 0"], -12.0),
            ("# GHz S RI R 50", ["5.0 0.5 0", "5.1 0.1 0"], -20.0),
        ],
    )
    def test_touchstone_summary_parses_s1p_formats(
        self, tmp_path: Path, header: str, rows: list[str], expected_min_db: float
    ) -> None:
        touchstone = tmp_path / "result.s1p"
        touchstone.write_text("\n".join(["! fixture", header, *rows]), encoding="utf-8")

        summary = drv.touchstone_summary(
            touchstone,
            target_frequencies_ghz=[5.05],
            threshold_db=-10,
        )

        assert summary["ok"] is True
        assert summary["available"] is True
        assert summary["row_count"] == 2
        assert summary["min"]["db"] == pytest.approx(expected_min_db, abs=0.02)
        assert summary["targets"][0]["target_ghz"] == 5.05
        assert summary["threshold_bandwidth_ghz"] == [5.1, 5.1]

    def test_touchstone_summary_reports_missing_file(self, tmp_path: Path) -> None:
        summary = drv.touchstone_summary(tmp_path / "missing.s1p")

        assert summary["ok"] is False
        assert summary["available"] is False
        assert summary["error_code"] == "FILE_NOT_FOUND"


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
        assert disconnected["ok"] is True
        assert disconnected["disconnected"] is True
        assert disconnected["cleanup"]["reason"] == "disconnect"
        assert FakeHfss.release_calls

    def test_launch_tracks_unique_new_aedt_pid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        driver = HfssDriver()
        pid_snapshots = [set(), {4242}]
        monkeypatch.delenv("ANSYSEM_ROOT261", raising=False)
        monkeypatch.setattr(driver, "detect_installed", lambda: [_install()])
        monkeypatch.setattr(drv, "_aedt_process_pids", lambda: pid_snapshots.pop(0) if pid_snapshots else {4242})
        monkeypatch.setattr(drv, "_pid_is_alive", lambda pid: pid == 4242)
        monkeypatch.setattr(drv, "_kill_pid", lambda pid: True)
        monkeypatch.setattr(
            drv,
            "_try_import_pyaedt",
            lambda: drv._PyaedtApi(Desktop=None, Hfss=FakeHfss, version="0.26.3"),
        )

        launched = driver.launch(ui_mode="no_gui")

        assert launched["ok"] is True
        assert launched["owned_aedt_pids"] == [4242]
        health = driver.query("session.health")
        assert health["ok"] is True
        assert health["owned_aedt_pid_alive"] == {"4242": True}
        driver.disconnect()

    def test_attach_mode_does_not_own_existing_aedt_pid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        driver = HfssDriver()
        monkeypatch.delenv("ANSYSEM_ROOT261", raising=False)
        monkeypatch.setattr(driver, "detect_installed", lambda: [_install()])
        monkeypatch.setattr(drv, "_aedt_process_pids", lambda: {4242})
        monkeypatch.setattr(
            drv,
            "_try_import_pyaedt",
            lambda: drv._PyaedtApi(Desktop=None, Hfss=FakeHfss, version="0.26.3"),
        )

        launched = driver.launch(ui_mode="no_gui", new_desktop=False)

        assert launched["ok"] is True
        assert launched["owned_aedt_pids"] == []
        driver.disconnect()

    def test_exec_timeout_quarantines_session_and_kills_owned_pid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        driver = HfssDriver()
        alive = {4242: True}
        killed: list[int] = []
        monkeypatch.delenv("ANSYSEM_ROOT261", raising=False)
        monkeypatch.setattr(FakeHfss, "runtime_pid", 4242)
        monkeypatch.setattr(driver, "detect_installed", lambda: [_install()])
        monkeypatch.setattr(drv, "_aedt_process_pids", lambda: set())
        monkeypatch.setattr(drv, "_pid_is_alive", lambda pid: alive.get(pid, False))

        def fake_kill(pid: int) -> bool:
            killed.append(pid)
            alive[pid] = False
            return True

        monkeypatch.setattr(drv, "_kill_pid", fake_kill)
        monkeypatch.setattr(
            drv,
            "_try_import_pyaedt",
            lambda: drv._PyaedtApi(Desktop=None, Hfss=FakeHfss, version="0.26.3"),
        )

        launched = driver.launch(ui_mode="no_gui", exec_timeout_s=0.001)
        assert launched["owned_aedt_pids"] == [4242]

        run = driver.run("import time\ntime.sleep(0.05)", label="hung-control")
        time.sleep(0.1)

        assert run["ok"] is False
        assert run["hung"] is True
        assert run["timeout"]["timeout_s"] == 0.001
        assert run["cleanup"]["reason"] == "timeout"
        assert killed == [4242]
        assert FakeHfss.release_calls
        assert driver.query("session.health")["connected"] is False

    def test_default_timeout_is_disabled_for_solve_snippets(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        driver = HfssDriver()
        monkeypatch.delenv("SIM_HFSS_EXEC_TIMEOUT_S", raising=False)

        timeout_s, source = driver._resolve_exec_timeout("hfss.analyze_setup('Setup1')", None)

        assert timeout_s is None
        assert source == "disabled:solve-snippet"

    def test_driver_option_exec_timeout_overrides_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        driver = HfssDriver()
        driver._launch_options = {"exec_timeout_s": "12.5"}
        monkeypatch.delenv("SIM_HFSS_EXEC_TIMEOUT_S", raising=False)

        timeout_s, source = driver._resolve_exec_timeout("hfss.project_name", None)

        assert timeout_s == 12.5
        assert source == "driver_option:exec_timeout_s"

    def test_evidence_queries(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        driver = HfssDriver()
        monkeypatch.delenv("ANSYSEM_ROOT261", raising=False)
        monkeypatch.setattr(driver, "detect_installed", lambda: [_install()])
        monkeypatch.setattr(
            drv,
            "_try_import_pyaedt",
            lambda: drv._PyaedtApi(Desktop=None, Hfss=FakeHfss, version="0.26.3"),
        )

        launched = driver.launch(ui_mode="no_gui", project=str(tmp_path / "demo.aedt"))
        assert launched["ok"] is True

        model = driver.query("hfss.model.summary")
        assert model["ok"] is True
        assert model["available"] is True
        assert model["object_count"] == 2
        assert model["solid_count"] == 1
        assert model["sheet_count"] == 1

        boundaries = driver.query("hfss.boundaries.summary")
        assert boundaries["boundary_count"] == 2
        assert boundaries["boundaries"][0]["name"] == "P1"
        assert boundaries["excitation_names"] == ["Port1"]

        setups = driver.query("hfss.setups.summary")
        assert setups["setup_count"] == 1
        assert setups["setups"][0]["sweeps"][0]["name"] == "Sweep1"

        messages = driver.query("hfss.messages")
        assert messages["available"] is True
        assert messages["count"] == 2
        assert messages["messages"][0]["severity"] == "error"
        assert set(messages["messages"][0]["objects"]) == {"Via1", "Substrate"}

        results_dir = tmp_path / "demo.aedtresults" / "HFSSDesign1.results"
        results_dir.mkdir(parents=True)
        (results_dir / "F1_SU.txt").write_text(
            "\n".join([
                "Frequency 5800000000.000000",
                "Success 1",
                "NumTets 123",
                "MatrixSize 456",
            ]),
            encoding="utf-8",
        )
        progress = driver.query("hfss.solution.progress")
        assert progress["available"] is True
        assert progress["completed_frequency_count"] == 1
        assert progress["latest"]["frequency_ghz"] == pytest.approx(5.8)
        assert progress["success_count"] == 1

        driver.disconnect()

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
    runtime_pid: int | None = None

    def __init__(self, **kwargs: object) -> None:
        type(self).last_kwargs = kwargs
        type(self).release_calls = []
        self.aedt_process_id = type(self).runtime_pid
        self.project_name = "DemoProject"
        self.project_file = str(kwargs.get("project") or "demo.aedt")
        self.project_path = "/tmp/demo"
        self.working_directory = "/tmp/demo"
        self.aedt_version_id = "2026.1"
        self.design_name = "HFSSDesign1"
        self.design_type = "HFSS"
        self.solution_type = "Modal"
        self.setup_names = ["Setup1"]
        self.excitation_names = ["Port1"]
        self.valid_design = True
        self.modeler = SimpleNamespace(
            object_names=["Box1", "PortSheet"],
            solid_names=["Box1"],
            sheet_names=["PortSheet"],
            objects={
                1: SimpleNamespace(name="Box1", material_name="vacuum", bounding_box=[0, 0, 0, 1, 1, 1]),
                2: SimpleNamespace(name="PortSheet", material_name="copper", bounding_box=[0, 0, 0, 0, 1, 1]),
            },
        )
        self.boundaries = [
            SimpleNamespace(name="P1", type="Lumped Port", props={"Objects": ["PortSheet"]}),
            SimpleNamespace(name="Radiation", type="Radiation", props={"Objects": ["Air"]}),
        ]
        self.setups = [
            SimpleNamespace(
                name="Setup1",
                props={"Frequency": "5.8GHz"},
                sweeps=[SimpleNamespace(name="Sweep1", type="Discrete", props={"RangeStart": "5GHz"})],
            )
        ]
        self.odesktop = FakeDesktop()
        self.desktop_class = SimpleNamespace()

    def release_desktop(self, **kwargs: object) -> None:
        type(self).release_calls.append(kwargs)


class FakeDesktop:
    def GetMessages(self, *_args: object) -> list[str]:
        return [
            "Error: Parts Via1 and Substrate intersect.",
            "Warning: Mesh refinement reached requested limit.",
        ]
