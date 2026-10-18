"""Win32 GUI automation backend for Flotherm (Qt application).

Proven automation path:
  1. Subprocess: pywinauto UIA expand() Macro > invoke() Play FloSCRIPT
     (invoke blocks because the file dialog is modal — subprocess times out, dialog stays open)
  2. Main process: raw Win32 ctypes to fill the file dialog and click Open

This separation is critical:
  - UIA invoke() throws COMError and corrupts COM state for the entire process
  - Running UIA in a subprocess isolates the corruption
  - Win32 ctypes for the standard file dialog works reliably from the main process

Phase 3 refactor: the generic enumerate / find-by-title / fill-file-dialog
primitives previously lived inline here; they now come from
``sim.gui._win32_dialog`` so every driver (fluent / comsol / mechanical)
can share the same implementation. The Flotherm-specific UIA menu trigger
and Message Dock readers stay here.
"""
from __future__ import annotations

import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from sim.gui._win32_dialog import (
    dismiss_windows_by_title_fragment,
    fill_file_dialog as _fill_file_dialog,
    find_dialog_by_title as _find_dialog,
    user32,
)

from ._helpers import tail_logfile_xml


def _drain(pipe) -> str:
    """Read whatever is buffered on a subprocess pipe without blocking forever."""
    if pipe is None:
        return ""
    try:
        return pipe.read().decode("utf-8", errors="replace").strip()
    except Exception:
        return ""

_UIA_MENU_TRIGGER = """\
import io, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from pywinauto import Desktop
from pywinauto.application import Application
deadline = time.monotonic() + 30
last_error = None
while True:
    try:
        main0 = next(
            w for w in Desktop(backend="uia").windows()
            if w.class_name() == "FloMainWindow"
        )
        app = Application(backend="uia").connect(process=main0.process_id())
        win = app.window(handle=main0.handle)
        break
    except Exception as exc:
        last_error = exc
        if time.monotonic() >= deadline:
            raise last_error
        time.sleep(0.5)
try:
    win.set_focus()
except Exception:
    pass
macro = win.child_window(control_type="MenuBar", found_index=0).child_window(title="Macro", control_type="MenuItem")
macro.expand()
time.sleep(0.5)
submenu = macro.child_window(control_type="Menu")
play = submenu.child_window(title_re=".*Play FloSCRIPT.*", control_type="MenuItem")
try:
    play.invoke()
except Exception:
    pass
print("triggered Macro > Play FloSCRIPT")
"""

_UIA_SOLVE_MENU_TRIGGER = r"""
import io, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from pywinauto import Desktop, mouse
from pywinauto.application import Application

deadline = time.monotonic() + 30
last_error = None
while True:
    try:
        main0 = next(
            w for w in Desktop(backend="uia").windows()
            if w.class_name() == "FloMainWindow"
        )
        app = Application(backend="uia").connect(process=main0.process_id())
        win = app.window(handle=main0.handle)
        break
    except Exception as exc:
        last_error = exc
        if time.monotonic() >= deadline:
            raise last_error
        time.sleep(0.5)

try:
    win.set_focus()
except Exception:
    pass

bar = win.child_window(control_type="MenuBar", found_index=0)
solve_menus = [
    child for child in bar.children()
    if child.window_text() == "Solve"
    and child.element_info.control_type == "MenuItem"
]
if not solve_menus:
    raise RuntimeError("Solve menu not found")

solve_menu = solve_menus[0]
solve_menu.expand()
time.sleep(0.5)
items = [
    child for child in solve_menu.descendants(control_type="MenuItem")
    if child.window_text() == "Solve"
]
if not items:
    names = [
        child.window_text() for child in solve_menu.descendants(control_type="MenuItem")
        if child.window_text()
    ]
    raise RuntimeError(f"Solve > Solve menu item not found; saw {names!r}")

try:
    items[0].invoke()
except Exception:
    pass

handled_save_project = False
save_project_error_dialog = False
canceled_save_project_after_error = False
deadline = time.monotonic() + 25
save_dialog_candidates = []

def _window_name(ctrl):
    try:
        return (ctrl.window_text() or "").strip()
    except Exception:
        return ""

def _save_project_dialogs():
    found = []
    for root in [Desktop(backend="uia"), win]:
        try:
            windows = root.windows() if root is not win else root.descendants(control_type="Window")
        except Exception:
            continue
        for candidate in windows:
            name = _window_name(candidate)
            if name:
                save_dialog_candidates.append(name)
            if name == "Save Project":
                found.append(candidate)
    return found

def _message_windows():
    found = []
    for root in [Desktop(backend="uia"), win]:
        try:
            windows = root.windows() if root is not win else root.descendants(control_type="Window")
        except Exception:
            continue
        for candidate in windows:
            name = _window_name(candidate)
            if "Message Window" in name:
                found.append(candidate)
    return found

def _click_button(dialog, name, *, physical=False):
    buttons = [
        child for child in dialog.descendants(control_type="Button")
        if _window_name(child) == name
    ]
    if not buttons:
        return False
    button = buttons[0]
    try:
        button.invoke()
    except Exception:
        pass
    if physical:
        time.sleep(0.2)
        try:
            dialog.set_focus()
        except Exception:
            pass
        try:
            rect = button.rectangle()
            mouse.click(
                button="left",
                coords=(int((rect.left + rect.right) / 2), int((rect.top + rect.bottom) / 2)),
            )
        except Exception:
            pass
    return True

def _close_message_windows():
    closed = False
    for message_window in _message_windows():
        try:
            message_window.close()
            closed = True
        except Exception:
            pass
        try:
            rect = message_window.rectangle()
            mouse.click(button="left", coords=(rect.right - 22, rect.top + 16))
            closed = True
        except Exception:
            pass
    if closed:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if not _message_windows():
                return True
            time.sleep(0.2)
    return not _message_windows()

def _close_save_project_dialog():
    remaining_save_dialog = next(iter(_save_project_dialogs()), None)
    if remaining_save_dialog is None:
        return True
    save_app = Application(backend="uia").connect(process=remaining_save_dialog.process_id())
    save_dialog = save_app.window(handle=remaining_save_dialog.handle)
    _click_button(save_dialog, "Cancel", physical=True)
    time.sleep(0.5)
    _close_message_windows()
    if next(iter(_save_project_dialogs()), None) is None:
        return True
    try:
        save_dialog.set_focus()
        save_dialog.type_keys("{ESC}")
    except Exception:
        pass
    time.sleep(0.5)
    if next(iter(_save_project_dialogs()), None) is None:
        return True
    try:
        save_dialog.close()
    except Exception:
        pass
    time.sleep(0.5)
    return next(iter(_save_project_dialogs()), None) is None

while time.monotonic() < deadline:
    save_dialog = next(iter(_save_project_dialogs()), None)
    if save_dialog is None:
        time.sleep(0.2)
        continue
    app = Application(backend="uia").connect(process=save_dialog.process_id())
    dialog = app.window(handle=save_dialog.handle)
    if not _click_button(dialog, "OK"):
        raise RuntimeError("Save Project dialog appeared but OK button was not found")
    handled_save_project = True

    message_deadline = time.monotonic() + 5
    while time.monotonic() < message_deadline:
        message_window = next(iter(_message_windows()), None)
        if message_window is None:
            time.sleep(0.2)
            continue
        save_project_error_dialog = True
        _close_message_windows()
        canceled_save_project_after_error = _close_save_project_dialog()
        break
    break

print(
    "triggered Solve > Solve; "
    f"handled_save_project={handled_save_project}; "
    f"save_project_error_dialog={save_project_error_dialog}; "
    f"canceled_save_project_after_error={canceled_save_project_after_error}"
)
if not handled_save_project and save_dialog_candidates:
    unique_candidates = list(dict.fromkeys(save_dialog_candidates))
    print(f"save_project_dialog_candidates={unique_candidates!r}")
"""

_UIA_CLEANUP_SOLVE_MODAL = r"""
import io, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from pywinauto import Desktop, mouse

def _name(ctrl):
    try:
        return (ctrl.window_text() or "").strip()
    except Exception:
        return ""

def _windows():
    try:
        return Desktop(backend="uia").windows()
    except Exception:
        return []

def _main_windows():
    return [w for w in _windows() if w.class_name() == "FloMainWindow"]

def _save_project_windows():
    return [w for w in _windows() if _name(w) == "Save Project"]

def _message_windows():
    found = [w for w in _windows() if "Message Window" in _name(w)]
    for main in _main_windows():
        try:
            found.extend(
                w for w in main.descendants(control_type="Window")
                if "Message Window" in _name(w)
            )
        except Exception:
            pass
    return found

def _click_button(dialog, name):
    for button in dialog.descendants(control_type="Button"):
        if _name(button) != name:
            continue
        try:
            dialog.set_focus()
        except Exception:
            pass
        time.sleep(0.1)
        rect = button.rectangle()
        mouse.click(
            button="left",
            coords=(int((rect.left + rect.right) / 2), int((rect.top + rect.bottom) / 2)),
        )
        return True
    return False

closed_save_project = False
closed_message_windows = False
deadline = time.monotonic() + 8
while time.monotonic() < deadline:
    progressed = False
    for message in _message_windows():
        try:
            message.set_focus()
            time.sleep(0.1)
            rect = message.rectangle()
            mouse.click(button="left", coords=(rect.right - 22, rect.top + 16))
            closed_message_windows = True
            progressed = True
        except Exception:
            pass
    if progressed:
        time.sleep(0.5)

    for save_dialog in _save_project_windows():
        try:
            if _click_button(save_dialog, "Cancel"):
                closed_save_project = True
                progressed = True
        except Exception:
            pass
    if progressed:
        time.sleep(0.5)

    if not _save_project_windows() and not _message_windows():
        break
    if not progressed:
        time.sleep(0.2)

print(
    f"cleanup_save_project={closed_save_project}; "
    f"cleanup_message_windows={closed_message_windows}; "
    f"remaining_save_project={len(_save_project_windows())}; "
    f"remaining_message_windows={len(_message_windows())}"
)
"""


def _dismiss_popups() -> list[str]:
    """Close any Message Window or error popups. Returns list of dismissed titles."""
    return dismiss_windows_by_title_fragment("Message")


_MESSAGE_DOCK_READ = r"""
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from pywinauto import Desktop
main = next((w for w in Desktop(backend="uia").windows()
             if w.class_name() == "FloMainWindow"), None)
if main:
    dock = next((d for d in main.descendants(control_type="Window")
                 if "Message Window" in (d.window_text() or "")), None)
    if dock:
        seen = set()
        for d in dock.descendants():
            t = (d.window_text() or "").strip()
            if t and len(t) > 3 and t not in seen:
                seen.add(t)
                print(t)
"""


def read_message_dock(timeout: float = 15) -> list[str]:
    """Return all text lines currently in Flotherm's Message Window dock.

    The dock is a ``flohelp::DockWidget`` embedded inside ``FloMainWindow``,
    not a top-level window, so the caller-side popup-dismiss machinery misses
    it. This helper enumerates the dock's UIA descendants and returns the
    text lines. Runs UIA in a subprocess to keep the main process's COM
    apartment clean (pywinauto enumeration has a history of COM pollution).
    """
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _MESSAGE_DOCK_READ],
            capture_output=True,
            timeout=timeout,
        )
        out = proc.stdout.decode("utf-8", errors="replace")
        return [ln.strip() for ln in out.splitlines() if ln.strip()]
    except Exception:
        return []


_DOCK_CLEAR = """
import time
from pywinauto import Desktop
main = next((w for w in Desktop(backend="uia").windows()
             if w.class_name() == "FloMainWindow"), None)
if main:
    dock = next((d for d in main.descendants(control_type="Window")
                 if "Message Window" in (d.window_text() or "")), None)
    if dock:
        for b in dock.descendants(control_type="Button"):
            if b.window_text() == "Clear":
                b.click_input(); time.sleep(0.4); break
"""


def _clear_message_dock(timeout: float = 5) -> None:
    """Click the Clear button in Flotherm's Message Window dock.

    Without this, the dock's deduplicated readback returns *every* error
    from prior plays in the same session, masking the actual outcome of
    the current play. Click via UIA in a subprocess (consistent with the
    other dock helpers, keeps COM apartment clean).
    """
    try:
        subprocess.run(
            [sys.executable, "-c", _DOCK_CLEAR],
            capture_output=True, timeout=timeout,
        )
    except Exception:
        pass


def _read_gui_log(install_root: str | None) -> list[dict]:
    """Return structured entries from the active Flotherm GUI session log."""
    if not install_root:
        return []
    try:
        return tail_logfile_xml(install_root)
    except Exception:
        return []


def _entry_key(entry: dict) -> tuple[str, str, str, str]:
    """Stable identity for subtracting a GUI-log baseline."""
    return (
        str(entry.get("code", "")),
        str(entry.get("severity", "")),
        str(entry.get("message", "")),
        str(entry.get("raw", "")),
    )


def _new_log_entries(before: list[dict], after: list[dict]) -> list[dict]:
    """Return entries present after playback but absent from the baseline."""
    remaining = Counter(_entry_key(entry) for entry in before)
    new: list[dict] = []
    for entry in after:
        key = _entry_key(entry)
        if remaining[key]:
            remaining[key] -= 1
            continue
        new.append(entry)
    return new


def play_floscript(
    script_path: str,
    timeout: float = 15,
    *,
    install_root: str | None = None,
) -> dict:
    """Trigger Macro > Play FloSCRIPT and submit a FloSCRIPT XML file.

    Returns dict with ``ok`` status and diagnostics. When Flotherm's
    Message Window dock records new ``ERROR``/``WARN`` lines during the
    play, they are surfaced as ``errors``/``warnings`` and ``ok`` is
    flipped to ``False`` — the dock captures runtime failures the CLI
    would otherwise miss (E/15002 etc.).

    The dock is cleared before each play because its readback is
    deduplicated set-style: stale errors from earlier plays would
    otherwise be reported again here and mask the current play's
    actual result.
    """
    if user32 is None:
        return {"ok": False, "error": "Not on Windows"}

    # Flotherm's standard file-open dialog rejects forward-slash separators
    # ("The file name is not valid"). The FloSCRIPT body itself accepts /,
    # but the WM_SETTEXT into the dialog edit control needs native form.
    script_path = str(Path(script_path))

    # Dismiss any existing popups
    dismissed = _dismiss_popups()

    gui_log_before = _read_gui_log(install_root)

    # Clear the embedded Message Window dock so post_dock readback only
    # contains errors/warnings from THIS play
    _clear_message_dock()
    pre_dock: set[str] = set()

    # Step 1: Launch UIA subprocess to open Play FloSCRIPT dialog
    # invoke() is modal so the subprocess will block — we kill it after timeout
    proc = subprocess.Popen(
        [sys.executable, "-c", _UIA_MENU_TRIGGER],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()

    # Surface subprocess output so silent failures (missing pywinauto, COM
    # error, Qt mismatch) don't reduce to a generic "dialog not found".
    sub_stderr = _drain(proc.stderr)
    sub_stdout = _drain(proc.stdout)

    # Step 2: Find the Play FloSCRIPT file dialog.
    # find_dialog already polls (up to 5s) so no sleep needed before it.
    dialog = _find_dialog("Play FloSCRIPT", timeout=5)
    if dialog is None:
        result = {
            "ok": False,
            "error": "Play FloSCRIPT dialog not found after menu trigger",
            "dismissed_popups": dismissed,
        }
        if sub_stderr:
            result["subprocess_stderr"] = sub_stderr
        if sub_stdout:
            result["subprocess_stdout"] = sub_stdout
        return result

    # Step 3: Fill and submit
    if not _fill_file_dialog(dialog, script_path):
        return {"ok": False, "error": "Failed to fill file dialog controls"}

    # Step 4: Wait for Flotherm to process the FloSCRIPT and render dock output.
    # Poll instead of sleeping: return as soon as new dock lines appear, up to 8s.
    import time as _t
    _deadline = _t.monotonic() + 8.0
    post_dock: list[str] = []
    while _t.monotonic() < _deadline:
        post_dock = read_message_dock()
        new_lines = [ln for ln in post_dock if ln not in pre_dock]
        if new_lines:
            break
        _t.sleep(0.3)
    else:
        post_dock = read_message_dock()
        new_lines = [ln for ln in post_dock if ln not in pre_dock]
    errors = [ln for ln in new_lines if "ERROR" in ln]
    warnings = [ln for ln in new_lines if "WARN" in ln]
    gui_log_after = _read_gui_log(install_root)
    gui_log_new = _new_log_entries(gui_log_before, gui_log_after)
    gui_log_errors = [
        entry for entry in gui_log_new
        if entry.get("severity") == "error"
    ]
    gui_log_warnings = [
        entry for entry in gui_log_new
        if entry.get("severity") == "warning"
    ]

    result = {
        "ok": not errors and not gui_log_errors,
        "method": "subprocess_uia_win32",
        "dismissed_popups": dismissed,
    }
    if errors:
        result["errors"] = errors
    if warnings:
        result["warnings"] = warnings
    if gui_log_new:
        result["gui_log"] = gui_log_new
    if gui_log_errors:
        result["gui_log_errors"] = gui_log_errors
    if gui_log_warnings:
        result["gui_log_warnings"] = gui_log_warnings
    return result


def trigger_solve_menu(
    timeout: float = 40,
    *,
    install_root: str | None = None,
) -> dict:
    """Trigger Flotherm's `Solve > Solve` GUI menu item.

    This is intentionally a low-level control primitive. It only reports
    whether the menu action was triggered and whether Flotherm logged
    immediate GUI errors. Higher-level solve polling remains in the driver.
    """
    if user32 is None:
        return {"ok": False, "error": "Not on Windows"}

    dismissed = _dismiss_popups()
    gui_log_before = _read_gui_log(install_root)
    _clear_message_dock()

    proc = subprocess.run(
        [sys.executable, "-c", _UIA_SOLVE_MENU_TRIGGER],
        capture_output=True,
        timeout=timeout,
    )
    sub_stderr = proc.stderr.decode("utf-8", errors="replace").strip()
    sub_stdout = proc.stdout.decode("utf-8", errors="replace").strip()
    save_project_error = "save_project_error_dialog=True" in sub_stdout

    cleanup_stdout = ""
    cleanup_stderr = ""
    if save_project_error:
        cleanup_proc = subprocess.run(
            [sys.executable, "-c", _UIA_CLEANUP_SOLVE_MODAL],
            capture_output=True,
            timeout=15,
        )
        cleanup_stdout = cleanup_proc.stdout.decode("utf-8", errors="replace").strip()
        cleanup_stderr = cleanup_proc.stderr.decode("utf-8", errors="replace").strip()

    time.sleep(1.0)
    dock_lines = read_message_dock(timeout=5)
    errors = [ln for ln in dock_lines if "ERROR" in ln]
    warnings = [ln for ln in dock_lines if "WARN" in ln]
    gui_log_after = _read_gui_log(install_root)
    gui_log_new = _new_log_entries(gui_log_before, gui_log_after)
    gui_log_errors = [
        entry for entry in gui_log_new
        if entry.get("severity") == "error"
    ]
    gui_log_warnings = [
        entry for entry in gui_log_new
        if entry.get("severity") == "warning"
    ]

    final_cleanup_stdout = ""
    final_cleanup_stderr = ""
    if save_project_error or errors or warnings:
        final_cleanup_proc = subprocess.run(
            [sys.executable, "-c", _UIA_CLEANUP_SOLVE_MODAL],
            capture_output=True,
            timeout=15,
        )
        final_cleanup_stdout = final_cleanup_proc.stdout.decode("utf-8", errors="replace").strip()
        final_cleanup_stderr = final_cleanup_proc.stderr.decode("utf-8", errors="replace").strip()

    result = {
        "ok": (
            proc.returncode == 0
            and not errors
            and not gui_log_errors
            and not save_project_error
        ),
        "method": "subprocess_uia_solve_menu",
        "dismissed_popups": dismissed,
    }
    if sub_stdout:
        result["subprocess_stdout"] = sub_stdout
        if "handled_save_project=True" in sub_stdout:
            result["handled_save_project_dialog"] = True
        if save_project_error:
            result["save_project_error_dialog"] = True
        if "canceled_save_project_after_error=True" in sub_stdout:
            result["canceled_save_project_after_error"] = True
    if sub_stderr:
        result["subprocess_stderr"] = sub_stderr
    if cleanup_stdout:
        result["cleanup_stdout"] = cleanup_stdout
        if "cleanup_save_project=True" in cleanup_stdout:
            result["cleanup_save_project_dialog"] = True
        if "cleanup_message_windows=True" in cleanup_stdout:
            result["cleanup_message_windows"] = True
    if cleanup_stderr:
        result["cleanup_stderr"] = cleanup_stderr
    if final_cleanup_stdout:
        result["final_cleanup_stdout"] = final_cleanup_stdout
        if "remaining_save_project=0" in final_cleanup_stdout:
            result["final_cleanup_save_project_clear"] = True
        if "remaining_message_windows=0" in final_cleanup_stdout:
            result["final_cleanup_message_windows_clear"] = True
    if final_cleanup_stderr:
        result["final_cleanup_stderr"] = final_cleanup_stderr
    if proc.returncode != 0:
        result["error"] = "Solve > Solve menu trigger failed"
        result["returncode"] = proc.returncode
    if errors:
        result["errors"] = errors
    if warnings:
        result["warnings"] = warnings
    if gui_log_new:
        result["gui_log"] = gui_log_new
    if gui_log_errors:
        result["gui_log_errors"] = gui_log_errors
    if gui_log_warnings:
        result["gui_log_warnings"] = gui_log_warnings
    return result
