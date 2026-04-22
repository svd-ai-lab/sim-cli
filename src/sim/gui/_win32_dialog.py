"""Generic Win32 ctypes helpers for standard Windows dialogs.

Extracted from drivers/flotherm/_win32_backend.py so every driver can reuse
the same proven path for interacting with modal dialogs without each
driver vendoring its own copy.

The scope is deliberately narrow:

  * enumerate top-level visible windows by title,
  * wait for a dialog whose title contains a substring,
  * fill a standard Windows file-open/save dialog (edit ctl 1148 + OK btn 1)
    using WM_SETTEXT + BM_CLICK,
  * send WM_CLOSE to a window,
  * send a plain button click by dialog-item id.

These primitives do **not** depend on the UIA backend — they only use
raw user32 messages. Higher-level semantic operations (find button by
text, navigate menus, etc.) belong in ``_pywinauto_tools.py``.

Non-Windows platforms: ``user32`` stays ``None`` and helpers return
safe defaults (``False`` / empty list) so import never explodes.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
import time


user32 = ctypes.windll.user32 if os.name == "nt" else None

# Windows messages we use
WM_SETTEXT = 0x000C
BM_CLICK = 0x00F5
WM_CLOSE = 0x0010

# Standard control ids for the common Windows file-open/save dialog template.
FILE_DIALOG_EDIT_CTL_ID = 1148
FILE_DIALOG_OK_BTN_ID = 1


def enum_visible_windows() -> list[tuple[int, str]]:
    """Return ``[(hwnd, title)]`` for all visible top-level windows.

    Returns an empty list off-Windows or if the enumeration fails.
    """
    if user32 is None:
        return []

    hwnds: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def _cb(hwnd, _lp):
        hwnds.append(hwnd)
        return True

    user32.EnumWindows(_cb, 0)

    out: list[tuple[int, str]] = []
    for hwnd in hwnds:
        if not user32.IsWindowVisible(hwnd):
            continue
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        if buf.value:
            out.append((hwnd, buf.value))
    return out


def find_dialog_by_title(title_substring: str, timeout: float = 10.0) -> int | None:
    """Poll the desktop for a visible window whose title contains
    ``title_substring``.

    Returns the first matching hwnd, or ``None`` on timeout.
    """
    if user32 is None:
        return None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for hwnd, title in enum_visible_windows():
            if title_substring in title:
                return hwnd
        time.sleep(0.3)
    return None


def fill_file_dialog(dialog_hwnd: int, file_path: str) -> bool:
    """Set ``file_path`` into the edit control and click OK on a standard
    Windows file-open/save dialog.

    Uses control ids 1148 (edit) and 1 (OK button) that are stable across
    the classic Win32 file dialog template. Returns ``True`` on success,
    ``False`` if either control is not found.
    """
    if user32 is None:
        return False
    edit = user32.GetDlgItem(dialog_hwnd, FILE_DIALOG_EDIT_CTL_ID)
    if not edit:
        return False
    user32.SendMessageW(edit, WM_SETTEXT, 0, ctypes.create_unicode_buffer(file_path))
    time.sleep(0.3)
    ok_btn = user32.GetDlgItem(dialog_hwnd, FILE_DIALOG_OK_BTN_ID)
    if not ok_btn:
        return False
    user32.SendMessageW(ok_btn, BM_CLICK, 0, 0)
    return True


def click_dialog_item(dialog_hwnd: int, ctl_id: int) -> bool:
    """Send BM_CLICK to the child control identified by ``ctl_id``.

    Generic counterpart to :func:`fill_file_dialog` for dialogs that only
    need a button click (OK, Cancel, Yes, No) and no text entry.
    """
    if user32 is None:
        return False
    btn = user32.GetDlgItem(dialog_hwnd, ctl_id)
    if not btn:
        return False
    user32.SendMessageW(btn, BM_CLICK, 0, 0)
    return True


def close_window(hwnd: int) -> bool:
    """Post WM_CLOSE to ``hwnd``. Returns ``True`` if the message was posted."""
    if user32 is None:
        return False
    return bool(user32.PostMessageW(hwnd, WM_CLOSE, 0, 0))


def dismiss_windows_by_title_fragment(fragment: str) -> list[str]:
    """Close every visible window whose title contains ``fragment`` via
    WM_CLOSE. Returns the titles that were dismissed.

    Intended for nuisance dialogs the caller knows the title pattern of
    (flotherm's 'Message', Fluent's 'Question', etc.). For semantic "click
    the OK button" use :mod:`sim.gui._pywinauto_tools` instead.
    """
    if user32 is None:
        return []
    dismissed: list[str] = []
    for hwnd, title in enum_visible_windows():
        if fragment in title:
            if close_window(hwnd):
                dismissed.append(title)
    if dismissed:
        time.sleep(0.5)
    return dismissed
