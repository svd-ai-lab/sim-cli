"""Session lifecycle regressions for the Flotherm driver."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from sim.driver import Diagnostic, LintResult
from sim_plugin_flotherm import FlothermDriver
import sim_plugin_flotherm.driver as flotherm_driver_module
from sim_plugin_flotherm._helpers import (
    detect_job_state,
    is_process_alive,
    read_solve_log,
)


def test_no_gui_mode_is_rejected() -> None:
    driver = FlothermDriver()

    with pytest.raises(RuntimeError, match="does not support ui_mode='no_gui'"):
        driver.launch(ui_mode="no_gui")


def test_is_process_alive_handles_empty_pid() -> None:
    assert is_process_alive(None) is False


def test_read_solve_log_detects_normal_exit(tmp_path: Path) -> None:
    project_dir = "Demo.ABC"
    logit = (
        tmp_path / project_dir / "DataSets" / "BaseSolution" / "PDTemp" / "logit"
    )
    logit.parent.mkdir(parents=True)
    logit.write_text(
        "solver output\nstatus 3 normal exit from main program MAINUU.\n",
        encoding="utf-8",
    )

    out = read_solve_log(str(tmp_path), project_dir)

    assert out["exists"] is True
    assert out["state"] == "succeeded"
    assert "normal exit" in out["tail"]


def test_read_solve_log_accepts_non_three_normal_exit(tmp_path: Path) -> None:
    project_dir = "Demo.ABC"
    logit = (
        tmp_path / project_dir / "DataSets" / "BaseSolution" / "PDTemp" / "logit"
    )
    logit.parent.mkdir(parents=True)
    logit.write_text(
        "solver output\nstatus 7 normal exit from main program MAINUU.\n",
        encoding="utf-8",
    )

    assert read_solve_log(str(tmp_path), project_dir)["state"] == "succeeded"


def test_detect_job_state_uses_logit_completion_even_when_process_alive(
    tmp_path: Path,
) -> None:
    project_dir = "Demo.ABC"
    logit = (
        tmp_path / project_dir / "DataSets" / "BaseSolution" / "PDTemp" / "logit"
    )
    logit.parent.mkdir(parents=True)
    logit.write_text(
        "solver output\nstatus 3 normal exit from main program MAINUU.\n",
        encoding="utf-8",
    )

    state, reasons = detect_job_state(
        workspace=str(tmp_path),
        project_dir=project_dir,
        pre_solve_snapshot={},
        process_pid=None,
        elapsed_s=1,
        timeout_s=30,
    )

    assert state == "succeeded"
    assert any("PDTemp/logit state: succeeded" in reason for reason in reasons)


def test_find_schema_dir_falls_back_to_installed_winxp_lib(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schema_dir = tmp_path / "WinXP" / "lib"
    schema_dir.mkdir(parents=True)
    (schema_dir / "FloSCRIPTSchema.xsd").write_text("<x/>", encoding="utf-8")
    monkeypatch.setattr(
        flotherm_driver_module,
        "find_installation",
        lambda: {"install_root": str(tmp_path), "version": "2504"},
    )

    assert FlothermDriver()._find_schema_dir() == schema_dir


def test_dispatch_xml_lints_before_gui_play(tmp_path: Path) -> None:
    script = tmp_path / "bad.xml"
    script.write_text(
        '<?xml version="1.0"?><xml_log_file version="1.0"><bad/></xml_log_file>',
        encoding="utf-8",
    )
    driver = FlothermDriver()
    driver._session = {
        "state": "ready",
        "workspace": str(tmp_path),
        "install_root": str(tmp_path),
    }

    def fake_lint(path: Path) -> LintResult:
        return LintResult(
            ok=False,
            diagnostics=[
                Diagnostic(level="error", message="Line 1: bad element", line=1),
            ],
        )

    def fail_if_called(path: str) -> dict:
        raise AssertionError("GUI playback should not run after lint errors")

    driver.lint = fake_lint  # type: ignore[method-assign]
    driver._play_floscript = fail_if_called  # type: ignore[method-assign]

    result = driver._dispatch(str(script))

    assert result["ok"] is False
    assert result["action"] == "lint_floscript"
    assert result["diagnostics"][0]["message"] == "Line 1: bad element"


def test_run_preserves_dispatch_diagnostics(tmp_path: Path) -> None:
    script = tmp_path / "bad.xml"
    script.write_text(
        '<?xml version="1.0"?><xml_log_file version="1.0"><bad/></xml_log_file>',
        encoding="utf-8",
    )
    driver = FlothermDriver()
    driver.probes = []
    driver._session = {
        "state": "ready",
        "workspace": str(tmp_path),
        "install_root": str(tmp_path),
    }
    driver.lint = lambda path: LintResult(  # type: ignore[method-assign]
        ok=False,
        diagnostics=[Diagnostic(level="error", message="schema says no")],
    )

    result = driver.run(str(script))

    assert result["ok"] is False
    assert result["diagnostics"][0]["message"] == "schema says no"


def test_dispatch_solve_menu_uses_gui_helper(tmp_path: Path) -> None:
    driver = FlothermDriver()
    driver._session = {
        "state": "ready",
        "workspace": str(tmp_path),
        "install_root": str(tmp_path),
    }

    def fake_solve_menu() -> dict:
        return {
            "ok": True,
            "method": "subprocess_uia_solve_menu",
            "subprocess_stdout": "triggered Solve > Solve; handled_save_project=True",
            "handled_save_project_dialog": True,
        }

    driver._trigger_solve_menu = fake_solve_menu  # type: ignore[method-assign]

    result = driver._dispatch("solve_menu")

    assert result["ok"] is True
    assert result["action"] == "solve_menu"
    assert result["gui"]["method"] == "subprocess_uia_solve_menu"
    assert result["gui"]["handled_save_project_dialog"] is True


def test_dispatch_save_as_generates_and_syncs_project(tmp_path: Path) -> None:
    driver = FlothermDriver()
    driver._session = {
        "state": "ready",
        "workspace": str(tmp_path),
        "install_root": str(tmp_path),
    }

    saved = tmp_path / "NamedProject.XYZ"
    group = saved / "PDProject" / "group"
    group.parent.mkdir(parents=True)
    group.write_text("project", encoding="utf-8")

    driver.lint = lambda path: LintResult(ok=True, diagnostics=[])  # type: ignore[method-assign]
    driver._play_floscript = lambda path: {"ok": True}  # type: ignore[method-assign]

    result = driver._dispatch("save_as NamedProject")

    assert result["ok"] is True
    assert result["action"] == "project_save_as"
    script = Path(result["script"]).read_text(encoding="utf-8")
    assert 'project_name="NamedProject"' in script
    assert 'save_with_results="true"' in script
    assert driver._project is not None
    assert driver._project["project_dir"] == "NamedProject.XYZ"


def test_dispatch_record_controls_generate_scripts(tmp_path: Path) -> None:
    driver = FlothermDriver()
    driver._session = {
        "state": "ready",
        "workspace": str(tmp_path),
        "install_root": str(tmp_path),
    }
    played: list[str] = []

    driver.lint = lambda path: LintResult(ok=True, diagnostics=[])  # type: ignore[method-assign]

    def fake_play(path: str) -> dict:
        played.append(Path(path).read_text(encoding="utf-8"))
        return {"ok": True}

    driver._play_floscript = fake_play  # type: ignore[method-assign]

    start = driver._dispatch(r"record_start C:\tmp\record.xml")
    stop = driver._dispatch("record_stop")

    assert start["ok"] is True
    assert start["action"] == "record_start"
    assert start["file_name"] == r"C:\tmp\record.xml"
    assert 'file_name="C:\\tmp\\record.xml"' in played[0]
    assert stop["ok"] is True
    assert stop["action"] == "record_stop"
    assert "<stop_record_script/>" in played[1]


def test_dispatch_xml_syncs_active_project_after_playback(tmp_path: Path) -> None:
    script = tmp_path / "ok.xml"
    script.write_text(
        '<?xml version="1.0"?><xml_log_file version="1.0"></xml_log_file>',
        encoding="utf-8",
    )
    older = tmp_path / "OldProject.ABC"
    newer = tmp_path / "NewProject.DEF"
    for project in (older, newer):
        group = project / "PDProject" / "group"
        group.parent.mkdir(parents=True)
        group.write_text("project", encoding="utf-8")
    os.utime(older / "PDProject" / "group", (1, 1))
    os.utime(newer / "PDProject" / "group", (2, 2))
    os.utime(older, (1, 1))
    os.utime(newer, (2, 2))

    driver = FlothermDriver()
    driver._session = {
        "state": "ready",
        "workspace": str(tmp_path),
        "install_root": str(tmp_path),
    }

    driver.lint = lambda path: LintResult(ok=True, diagnostics=[])  # type: ignore[method-assign]
    driver._play_floscript = lambda path: {"ok": True}  # type: ignore[method-assign]

    result = driver._dispatch(str(script))

    assert result["ok"] is True
    assert driver._project is not None
    assert driver._project["project_dir"] == "NewProject.DEF"
    assert driver._project["source"] == "workspace_discovery"
    assert driver._session["active_project"] == "NewProject.DEF"
