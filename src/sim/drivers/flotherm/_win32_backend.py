"""Win32 GUI automation backend for Flotherm.

Automates: Macro > Play FloSCRIPT → file dialog → FloSCRIPT XML path.
Runs inside the sim-server process (interactive desktop session required).
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import time

user32 = ctypes.windll.user32

# Win32 constants
WM_SETTEXT = 0x000C
BM_CLICK = 0x00F5
WM_COMMAND = 0x0111
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
VK_RETURN = 0x0D


def find_flotherm_window(timeout: float = 10) -> int:
    """Find the FloMainWindow handle."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        hwnd = user32.FindWindowW(None, None)
        while hwnd:
            buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, buf, 256)
            if "FloMainWindow" in buf.value:
                return hwnd
            hwnd = user32.FindWindowExW(None, hwnd, None, None)
        # Try by window title containing "Flotherm"
        hwnd = user32.FindWindowW(None, None)
        while hwnd:
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            if "Flotherm" in buf.value or "FloTHERM" in buf.value:
                if user32.IsWindowVisible(hwnd):
                    return hwnd
            hwnd = user32.FindWindowExW(None, hwnd, None, None)
        time.sleep(0.5)
    raise RuntimeError("FloMainWindow not found")


def _enum_windows_callback_factory(results: list):
    """Create a callback for EnumWindows."""
    @ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def callback(hwnd, lparam):
        results.append(hwnd)
        return True
    return callback


def find_dialog(title_substring: str, timeout: float = 10) -> int:
    """Find a dialog window by title substring."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        results = []
        cb = _enum_windows_callback_factory(results)
        user32.EnumWindows(cb, 0)
        for hwnd in results:
            if not user32.IsWindowVisible(hwnd):
                continue
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            if title_substring.lower() in buf.value.lower():
                return hwnd
        time.sleep(0.3)
    raise RuntimeError(f"Dialog '{title_substring}' not found within {timeout}s")


def play_floscript(script_path: str, timeout: float = 15) -> dict:
    """Trigger Macro > Play FloSCRIPT and feed it the script path.

    Steps:
    1. Find Flotherm main window
    2. Send Alt+M (Macro menu) then P (Play FloSCRIPT)
    3. Wait for file dialog
    4. Set filename and click Open
    """
    import subprocess as sp

    # Step 1: Find main window
    hwnd = find_flotherm_window(timeout=10)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.5)

    # Step 2: Use keyboard to open Macro > Play FloSCRIPT
    # Alt key
    VK_MENU = 0x12
    VK_M = 0x4D  # 'M' for Macro
    VK_P = 0x50  # 'P' for Play

    # Press Alt
    user32.keybd_event(VK_MENU, 0, 0, 0)
    time.sleep(0.1)
    user32.keybd_event(VK_M, 0, 0, 0)
    user32.keybd_event(VK_M, 0, 2, 0)  # key up
    user32.keybd_event(VK_MENU, 0, 2, 0)  # key up
    time.sleep(0.5)

    # Press P for Play FloSCRIPT
    user32.keybd_event(VK_P, 0, 0, 0)
    user32.keybd_event(VK_P, 0, 2, 0)
    time.sleep(1.0)

    # Step 3: Find the file dialog
    try:
        dialog = find_dialog("Play FloSCRIPT", timeout=timeout)
    except RuntimeError:
        # Try alternate title
        dialog = find_dialog("Open", timeout=3)

    # Step 4: Find the filename edit control (control ID 1148 = standard file dialog)
    edit = user32.GetDlgItem(dialog, 1148)
    if not edit:
        # Try combo box edit (control ID 1148 is inside ComboBoxEx32)
        combo = user32.GetDlgItem(dialog, 1148)
        if combo:
            edit = combo
        else:
            raise RuntimeError("Cannot find filename edit control in dialog")

    # Set the filename
    path_buf = ctypes.create_unicode_buffer(script_path)
    user32.SendMessageW(edit, WM_SETTEXT, 0, path_buf)
    time.sleep(0.3)

    # Step 5: Click Open button (control ID 1 = IDOK)
    open_btn = user32.GetDlgItem(dialog, 1)
    if not open_btn:
        raise RuntimeError("Cannot find Open button in dialog")
    user32.SendMessageW(open_btn, BM_CLICK, 0, 0)

    return {"ok": True, "dialog_hwnd": dialog, "main_hwnd": hwnd}
