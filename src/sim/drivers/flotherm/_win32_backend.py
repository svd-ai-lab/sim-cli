"""Win32 GUI automation backend for Flotherm (Qt application).

Proven automation path:
  1. Subprocess: pywinauto UIA expand() Macro > invoke() Play FloSCRIPT
     (invoke blocks because the file dialog is modal — subprocess times out, dialog stays open)
  2. Main process: raw Win32 ctypes to fill the file dialog and click Open

This separation is critical:
  - UIA invoke() throws COMError and corrupts COM state for the entire process
  - Running UIA in a subprocess isolates the corruption
  - Win32 ctypes for the standard file dialog works reliably from the main process
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
import subprocess
import sys
import time


user32 = ctypes.windll.user32 if os.name == "nt" else None

WM_SETTEXT = 0x000C
BM_CLICK = 0x00F5
WM_CLOSE = 0x0010

_UIA_MENU_TRIGGER = """\
import time
from pywinauto.application import Application
app = Application(backend="uia").connect(title_re=".*Simcenter Flotherm.*", found_index=0)
win = app.window(title_re=".*Simcenter Flotherm.*", found_index=0)
macro = win.child_window(control_type="MenuBar", found_index=0).child_window(title="Macro", control_type="MenuItem")
macro.expand()
time.sleep(0.5)
submenu = macro.child_window(control_type="Menu")
play = submenu.child_window(title_re=".*Play FloSCRIPT.*", control_type="MenuItem")
try:
    play.invoke()
except Exception:
    pass
"""


def _enum_visible_windows() -> list[tuple[int, str]]:
    """Return [(hwnd, title)] for all visible windows."""
    results: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def cb(hwnd, _lp):
        results.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    out = []
    for hwnd in results:
        if not user32.IsWindowVisible(hwnd):
            continue
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        if buf.value:
            out.append((hwnd, buf.value))
    return out


def _dismiss_popups() -> list[str]:
    """Close any Message Window or error popups. Returns list of dismissed titles."""
    dismissed = []
    for hwnd, title in _enum_visible_windows():
        if "Message" in title:
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            dismissed.append(title)
    if dismissed:
        time.sleep(0.5)
    return dismissed


def _find_dialog(title_substring: str, timeout: float = 10) -> int | None:
    """Poll for a dialog window containing title_substring."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for hwnd, title in _enum_visible_windows():
            if title_substring in title:
                return hwnd
        time.sleep(0.3)
    return None


def _fill_file_dialog(dialog_hwnd: int, file_path: str) -> bool:
    """Set filename and click Open in a standard Windows file dialog."""
    edit = user32.GetDlgItem(dialog_hwnd, 1148)
    if not edit:
        return False
    user32.SendMessageW(edit, WM_SETTEXT, 0, ctypes.create_unicode_buffer(file_path))
    time.sleep(0.3)
    ok_btn = user32.GetDlgItem(dialog_hwnd, 1)
    if not ok_btn:
        return False
    user32.SendMessageW(ok_btn, BM_CLICK, 0, 0)
    return True


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


def play_floscript(script_path: str, timeout: float = 15) -> dict:
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

    # Dismiss any existing popups
    dismissed = _dismiss_popups()

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

    time.sleep(1.0)

    # Step 2: Find the Play FloSCRIPT file dialog
    dialog = _find_dialog("Play FloSCRIPT", timeout=5)
    if dialog is None:
        return {
            "ok": False,
            "error": "Play FloSCRIPT dialog not found after menu trigger",
            "dismissed_popups": dismissed,
        }

    # Step 3: Fill and submit
    if not _fill_file_dialog(dialog, script_path):
        return {"ok": False, "error": "Failed to fill file dialog controls"}

    # Step 4: give Flotherm a beat to render any runtime errors in the dock
    time.sleep(1.5)
    post_dock = read_message_dock()
    new_lines = [ln for ln in post_dock if ln not in pre_dock]
    errors = [ln for ln in new_lines if "ERROR" in ln]
    warnings = [ln for ln in new_lines if "WARN" in ln]

    result = {
        "ok": not errors,
        "method": "subprocess_uia_win32",
        "dismissed_popups": dismissed,
    }
    if errors:
        result["errors"] = errors
    if warnings:
        result["warnings"] = warnings
    return result
