"""Locate COMSOL Java Shell in a UIA snapshot."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
import subprocess
import sys
import textwrap
from typing import Iterable

from .target import DesktopTarget


class JavaShellError(RuntimeError):
    """Raised when the Java Shell channel cannot be located."""

    def __init__(self, code: str, message: str, artifacts: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.artifacts = artifacts or {}

    def to_dict(self) -> dict:
        return {
            "ok": False,
            "status": self.code,
            "error": self.message,
            "artifacts": self.artifacts,
        }


@dataclass(frozen=True)
class JavaShellChannel:
    target: DesktopTarget
    pane_handle: int | None
    input_handle: int | None
    input_control_type: str
    input_class_name: str = ""
    input_rect: list[int] | None = None

    def to_dict(self) -> dict:
        return {
            "target": self.target.to_dict(),
            "pane_handle": self.pane_handle,
            "input_handle": self.input_handle,
            "input_control_type": self.input_control_type,
            "input_class_name": self.input_class_name,
            "input_rect": self.input_rect,
            "exec_language": "java-shell",
        }


def _iter_nodes(node: dict) -> Iterable[dict]:
    yield node
    for child in (node.get("children") or node.get("controls") or []):
        yield from _iter_nodes(child)


def _node_name(node: dict) -> str:
    return str(node.get("name") or "")


def _control_type(node: dict) -> str:
    return str(node.get("control_type") or "")


def _class_name(node: dict) -> str:
    return str(node.get("class_name") or "")


def _node_handle(node: dict) -> int | None:
    raw = node.get("handle")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value or None


def _is_java_shell_node(node: dict) -> bool:
    name = _node_name(node).lower()
    return "java shell" in name or ("java" in name and "shell" in name)


def _is_editable(node: dict) -> bool:
    return _control_type(node).lower() in {"edit", "document"}


def _editable_rank(node: dict) -> tuple[int, int]:
    """Prefer the actual Java Shell input editor over output documents."""

    ctype = _control_type(node).lower()
    class_name = _class_name(node).lower()
    name = _node_name(node).lower()
    if class_name == "syntaxeditor":
        return (0, 0)
    if "input" in name or "command" in name:
        return (1, 0)
    if ctype == "edit":
        return (2, 0)
    if ctype == "document":
        return (3, 0)
    return (9, 0)


def find_java_shell_in_snapshot(
    snapshot: dict,
    target: DesktopTarget,
) -> JavaShellChannel:
    """Find Java Shell pane and input control from a UIA snapshot dict."""

    windows = snapshot.get("windows") or []
    target_window = None
    for window in windows:
        if int(window.get("hwnd") or 0) == target.hwnd:
            target_window = window
            break
    if target_window is None:
        raise JavaShellError(
            "target_not_found",
            f"Resolved target hwnd={target.hwnd} was not present in the UIA snapshot.",
        )

    panes = [node for node in _iter_nodes(target_window) if _is_java_shell_node(node)]
    if not panes:
        raise JavaShellError(
            "shell_not_visible",
            "Java Shell was not found. Open COMSOL Desktop > Home > Windows > Java Shell, then retry.",
        )

    # Prefer the deepest/last matching node; docked panes often have a parent
    # group and a named child, and the child's descendants are more precise.
    pane = panes[-1]
    edits = [node for node in _iter_nodes(pane) if _is_editable(node)]
    if not edits:
        raise JavaShellError(
            "input_not_found",
            "Java Shell was found, but no Edit/Document input control was found inside it.",
        )
    edit = sorted(enumerate(edits), key=lambda pair: (_editable_rank(pair[1]), -pair[0]))[0][1]
    return JavaShellChannel(
        target=target,
        pane_handle=_node_handle(pane),
        input_handle=_node_handle(edit),
        input_control_type=_control_type(edit),
        input_class_name=_class_name(edit),
        input_rect=edit.get("rect"),
    )


def _snapshot_for_target(target: DesktopTarget, max_depth: int = 8) -> dict:
    try:
        from sim.gui import _pywinauto_tools  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise JavaShellError(
            "uia_unavailable",
            f"sim.gui UIA helpers are unavailable: {exc}",
        ) from exc
    result = _pywinauto_tools.snapshot_uia_tree((), max_depth=max_depth)
    if not result.get("ok"):
        raise JavaShellError(
            "snapshot_failed",
            str(result.get("error") or "failed to snapshot UIA tree"),
        )
    return result


def _find_java_shell_live(
    target: DesktopTarget,
    timeout_s: float = 15,
    *,
    try_open: bool = True,
) -> JavaShellChannel:
    if os.name != "nt":
        raise JavaShellError("uia_unavailable", "COMSOL Desktop attach requires Windows.")
    script = textwrap.dedent(
        """
        import json
        import sys
        PARAMS = json.loads(sys.argv[1])

        def emit(payload):
            print(json.dumps(payload, ensure_ascii=True))

        try:
            from pywinauto import Application
        except Exception as exc:
            emit({"ok": False, "status": "uia_unavailable", "error": f"pywinauto import failed: {exc}"})
            raise SystemExit(0)

        def scan(win):
            shell_panes = []
            syntax_editors = []
            edits = []
            for control in win.descendants():
                try:
                    name = control.window_text() or ""
                    ctype = control.element_info.control_type or ""
                    class_name = getattr(control.element_info, "class_name", "") or ""
                    rect_obj = control.rectangle()
                    rect = [rect_obj.left, rect_obj.top, rect_obj.right, rect_obj.bottom]
                except Exception:
                    continue
                lowered = name.lower()
                if "java" in lowered and "shell" in lowered:
                    shell_panes.append({"handle": getattr(control, "handle", 0) or 0, "rect": rect, "control_type": ctype, "class_name": class_name})
                if ctype == "Edit" and class_name == "SyntaxEditor":
                    syntax_editors.append({"handle": getattr(control, "handle", 0) or 0, "rect": rect, "control_type": ctype, "class_name": class_name})
                elif ctype == "Edit" and ("input" in lowered or "command" in lowered):
                    edits.append({"handle": getattr(control, "handle", 0) or 0, "rect": rect, "control_type": ctype, "class_name": class_name})
            candidates = syntax_editors or edits
            return shell_panes, candidates

        def click_java_shell_button(win):
            for control in win.descendants():
                try:
                    name = control.window_text() or ""
                    ctype = control.element_info.control_type or ""
                    class_name = getattr(control.element_info, "class_name", "") or ""
                except Exception:
                    continue
                if name == "Java Shell" and ctype == "Button":
                    try:
                        control.click_input()
                        return {"clicked": True, "class_name": class_name}
                    except Exception as exc:
                        return {"clicked": False, "error": str(exc), "class_name": class_name}
            return {"clicked": False, "error": "Java Shell button not found"}

        try:
            import time
            app = Application(backend="uia").connect(handle=int(PARAMS["hwnd"]))
            win = app.window(handle=int(PARAMS["hwnd"]))
            shell_panes, candidates = scan(win)
            opened = None
            if not candidates and PARAMS.get("try_open"):
                opened = click_java_shell_button(win)
                if opened.get("clicked"):
                    time.sleep(0.8)
                    shell_panes, candidates = scan(win)
            if not shell_panes and not candidates:
                emit({"ok": False, "status": "shell_not_visible", "error": "Java Shell was not found. Open COMSOL Desktop > Home > Windows > Java Shell, then retry.", "open_attempt": opened})
                raise SystemExit(0)
            if not candidates:
                emit({"ok": False, "status": "input_not_found", "error": "Java Shell was found, but no SyntaxEditor/Edit input control was found.", "open_attempt": opened})
                raise SystemExit(0)
            if not shell_panes:
                shell_panes = [{"handle": 0, "rect": None, "control_type": "", "class_name": ""}]
            emit({"ok": True, "pane": shell_panes[-1], "input": candidates[-1]})
        except Exception as exc:
            emit({"ok": False, "status": "snapshot_failed", "error": str(exc)})
        """
    ).strip()
    try:
        proc = subprocess.run(
            [sys.executable, "-c", script, json.dumps({"hwnd": target.hwnd, "try_open": try_open})],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        raise JavaShellError("snapshot_failed", f"live Java Shell scan timed out after {timeout_s}s") from exc
    lines = [line for line in (proc.stdout or "").splitlines() if line.strip()]
    if proc.returncode != 0 and not lines:
        raise JavaShellError("snapshot_failed", (proc.stderr or "").strip() or f"live scan exited {proc.returncode}")
    if not lines:
        raise JavaShellError("snapshot_failed", "live Java Shell scan emitted no JSON")
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise JavaShellError("snapshot_failed", f"live scan emitted invalid JSON: {lines[-1]!r}") from exc
    if not payload.get("ok"):
        raise JavaShellError(str(payload.get("status") or "input_not_found"), str(payload.get("error") or "Java Shell input not found"))
    pane = payload["pane"]
    edit = payload["input"]
    return JavaShellChannel(
        target=target,
        pane_handle=int(pane.get("handle") or 0) or None,
        input_handle=int(edit.get("handle") or 0) or None,
        input_control_type=str(edit.get("control_type") or ""),
        input_class_name=str(edit.get("class_name") or ""),
        input_rect=edit.get("rect"),
    )


def find_java_shell(
    target: DesktopTarget,
    *,
    snapshot: dict | None = None,
    max_depth: int = 8,
) -> JavaShellChannel:
    """Locate a Java Shell channel for a resolved COMSOL Desktop target."""

    if snapshot is not None:
        return find_java_shell_in_snapshot(snapshot, target)
    try:
        return find_java_shell_in_snapshot(_snapshot_for_target(target, max_depth), target)
    except JavaShellError as exc:
        if exc.code not in {"input_not_found", "shell_not_visible"}:
            raise
        return _find_java_shell_live(target)
