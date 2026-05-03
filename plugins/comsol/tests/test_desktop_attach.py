from __future__ import annotations

import json
from pathlib import Path

import pytest

from sim_plugin_comsol.desktop_attach.audit import append_audit
from sim_plugin_comsol.desktop_attach.shell import (
    JavaShellError,
    JavaShellChannel,
    find_java_shell_in_snapshot,
)
from sim_plugin_comsol.desktop_attach.submit import SubmitError, validate_guardrail
from sim_plugin_comsol.desktop_attach.target import (
    DesktopSelector,
    DesktopTarget,
    TargetResolutionError,
    find_desktops,
    resolve_target,
)


def _windows():
    return [
        {"hwnd": 1, "pid": 10, "proc": "notepad.exe", "title": "notes", "rect": [0, 0, 1, 1]},
        {
            "hwnd": 2,
            "pid": 20,
            "proc": "comsol.exe",
            "title": "COMSOL Multiphysics 6.4 - user_model.mph",
            "rect": [0, 0, 100, 100],
        },
        {
            "hwnd": 3,
            "pid": 30,
            "proc": "comsol.exe",
            "title": "Connect to COMSOL Multiphysics Server",
            "rect": [0, 0, 100, 100],
        },
    ]


def test_find_desktops_filters_comsol_and_dialogs():
    targets = find_desktops(windows_provider=_windows)
    assert len(targets) == 1
    assert targets[0].desktop_pid == 20
    assert targets[0].to_dict()["lifecycle_owner"] == "external"
    assert targets[0].to_dict()["control_channel"] == "comsol.java-shell-uia"


def test_find_desktops_accepts_saved_model_title_suffix():
    def provider():
        return [
            {
                "hwnd": 6,
                "pid": 60,
                "proc": "ComsolUI.exe",
                "title": "Untitled.mph - COMSOL Multiphysics",
                "rect": [0, 0, 100, 100],
            }
        ]

    targets = find_desktops(windows_provider=provider)
    assert len(targets) == 1
    assert targets[0].desktop_pid == 60


def test_find_desktops_ignores_browser_pages_about_comsol():
    def provider():
        return [
            {
                "hwnd": 5,
                "pid": 50,
                "proc": "chrome.exe",
                "title": "sim-plugin-comsol: Driver plugin for sim-cli - Google Chrome",
                "rect": [0, 0, 100, 100],
            }
        ]

    assert find_desktops(windows_provider=provider) == []


def test_resolve_target_rejects_ambiguous():
    def provider():
        return _windows() + [
            {
                "hwnd": 4,
                "pid": 40,
                "proc": "comsol.exe",
                "title": "COMSOL Multiphysics 6.4 - other.mph",
                "rect": [0, 0, 100, 100],
            }
        ]

    with pytest.raises(TargetResolutionError) as exc:
        resolve_target(windows_provider=provider)
    assert exc.value.code == "target_ambiguous"
    assert len(exc.value.candidates) == 2


def test_resolve_target_can_exclude_known_pids():
    selector = DesktopSelector(exclude_pids=frozenset({20}))
    with pytest.raises(TargetResolutionError) as exc:
        resolve_target(selector, windows_provider=_windows)
    assert exc.value.code == "target_not_found"


def _snapshot():
    return {
        "ok": True,
        "windows": [
            {
                "hwnd": 2,
                "pid": 20,
                "proc": "comsol.exe",
                "title": "COMSOL Multiphysics 6.4 - user_model.mph",
                "controls": [
                    {"name": "Model Builder", "control_type": "Pane", "handle": 100},
                    {
                        "name": "Java Shell",
                        "control_type": "Pane",
                        "handle": 200,
                        "children": [
                            {"name": "Output", "control_type": "Document", "handle": 201},
                            {
                                "name": "",
                                "control_type": "Edit",
                                "handle": 202,
                                "class_name": "SyntaxEditor",
                                "rect": [441, 745, 795, 765],
                            },
                        ],
                    },
                ],
            }
        ],
    }


def test_find_java_shell_uses_last_editable_descendant():
    target = DesktopTarget(20, 2, "COMSOL Multiphysics 6.4 - user_model.mph", "comsol.exe")
    channel = find_java_shell_in_snapshot(_snapshot(), target)
    assert channel.pane_handle == 200
    assert channel.input_handle == 202
    assert channel.input_control_type == "Edit"
    assert channel.input_class_name == "SyntaxEditor"
    assert channel.input_rect == [441, 745, 795, 765]


def test_find_java_shell_prefers_syntax_editor_over_later_document():
    target = DesktopTarget(20, 2, "COMSOL Multiphysics 6.4 - user_model.mph", "comsol.exe")
    snapshot = _snapshot()
    snapshot["windows"][0]["controls"][1]["children"].append(
        {"name": "Late output", "control_type": "Document", "handle": 203}
    )
    channel = find_java_shell_in_snapshot(snapshot, target)
    assert channel.input_handle == 202


def test_find_java_shell_reports_missing_shell():
    target = DesktopTarget(20, 2, "COMSOL Multiphysics 6.4 - user_model.mph", "comsol.exe")
    snapshot = _snapshot()
    snapshot["windows"][0]["controls"] = []
    with pytest.raises(JavaShellError) as exc:
        find_java_shell_in_snapshot(snapshot, target)
    assert exc.value.code == "shell_not_visible"


def test_guardrail_allows_model_lines_and_comments():
    validate_guardrail(
        """
        // comment
        model.param().set("probe_x", "1");

        model.component("comp1").geom().run();
        """
    )


def test_guardrail_rejects_non_model_lines():
    with pytest.raises(SubmitError) as exc:
        validate_guardrail('ModelUtil.showProgress(true);')
    assert exc.value.code == "guardrail_rejected"


def test_append_audit_writes_capped_record(tmp_path: Path):
    target = DesktopTarget(20, 2, "COMSOL Multiphysics 6.4 - user_model.mph", "comsol.exe")
    channel = JavaShellChannel(target=target, pane_handle=200, input_handle=202, input_control_type="Edit")
    path = append_audit(channel, 'model.param().set("probe_x", "1");', "submitted", audit_dir=tmp_path)
    row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert row["desktop_pid"] == 20
    assert row["exec_language"] == "java-shell"
    assert row["status"] == "submitted"
    assert row["code_sha256"]
