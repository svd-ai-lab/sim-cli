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


def play_floscript(script_path: str, timeout: float = 15) -> dict:
    """Trigger Macro > Play FloSCRIPT and submit a FloSCRIPT XML file.

    Returns dict with ``ok`` status and diagnostics.
    """
    if user32 is None:
        return {"ok": False, "error": "Not on Windows"}

    # Dismiss any existing popups
    dismissed = _dismiss_popups()

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

    return {"ok": True, "method": "subprocess_uia_win32", "dismissed_popups": dismissed}
