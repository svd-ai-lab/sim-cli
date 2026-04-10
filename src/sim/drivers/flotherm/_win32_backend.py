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
MF_BYPOSITION = 0x0400
MF_BYCOMMAND = 0x0000
MIIM_ID = 0x00000002
MIIM_SUBMENU = 0x00000004
MIIM_STRING = 0x00000040


class MENUITEMINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.wintypes.UINT),
        ("fMask", ctypes.wintypes.UINT),
        ("fType", ctypes.wintypes.UINT),
        ("fState", ctypes.wintypes.UINT),
        ("wID", ctypes.wintypes.UINT),
        ("hSubMenu", ctypes.wintypes.HMENU),
        ("hbmpChecked", ctypes.wintypes.HBITMAP),
        ("hbmpUnchecked", ctypes.wintypes.HBITMAP),
        ("dwItemData", ctypes.POINTER(ctypes.wintypes.ULONG)),
        ("dwTypeData", ctypes.wintypes.LPWSTR),
        ("cch", ctypes.wintypes.UINT),
        ("hbmpItem", ctypes.wintypes.HBITMAP),
    ]


def _enum_windows() -> list[int]:
    """Enumerate all top-level windows."""
    results = []
    @ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def callback(hwnd, lparam):
        results.append(hwnd)
        return True
    user32.EnumWindows(callback, 0)
    return results


def _get_window_text(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def _get_class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def find_flotherm_window(timeout: float = 10) -> int:
    """Find the Flotherm main window handle."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for hwnd in _enum_windows():
            if not user32.IsWindowVisible(hwnd):
                continue
            title = _get_window_text(hwnd)
            if "Simcenter Flotherm" in title or "FloTHERM" in title:
                return hwnd
        time.sleep(0.5)
    raise RuntimeError("Flotherm window not found")


def find_dialog(title_substring: str, timeout: float = 10) -> int:
    """Find a dialog window by title substring."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for hwnd in _enum_windows():
            if not user32.IsWindowVisible(hwnd):
                continue
            title = _get_window_text(hwnd)
            if title_substring.lower() in title.lower():
                return hwnd
        time.sleep(0.3)
    raise RuntimeError(f"Dialog '{title_substring}' not found within {timeout}s")


def _get_menu_item_text(hmenu: int, index: int) -> str:
    """Get menu item text by position."""
    buf = ctypes.create_unicode_buffer(256)
    mii = MENUITEMINFOW()
    mii.cbSize = ctypes.sizeof(MENUITEMINFOW)
    mii.fMask = MIIM_STRING
    mii.dwTypeData = buf
    mii.cch = 256
    user32.GetMenuItemInfoW(hmenu, index, True, ctypes.byref(mii))
    return buf.value


def _find_menu_item(hmenu: int, text_substring: str) -> tuple[int, int] | None:
    """Find menu item by text. Returns (position, command_id) or None."""
    count = user32.GetMenuItemCount(hmenu)
    for i in range(count):
        label = _get_menu_item_text(hmenu, i)
        if text_substring.lower() in label.lower().replace("&", ""):
            # Get the command ID
            mii = MENUITEMINFOW()
            mii.cbSize = ctypes.sizeof(MENUITEMINFOW)
            mii.fMask = MIIM_ID | MIIM_SUBMENU
            user32.GetMenuItemInfoW(hmenu, i, True, ctypes.byref(mii))
            return (i, mii.wID)
    return None


def _find_submenu(hmenu: int, text_substring: str) -> int | None:
    """Find a submenu by text. Returns submenu handle or None."""
    count = user32.GetMenuItemCount(hmenu)
    for i in range(count):
        label = _get_menu_item_text(hmenu, i)
        if text_substring.lower() in label.lower().replace("&", ""):
            sub = user32.GetSubMenu(hmenu, i)
            if sub:
                return sub
    return None


def _dump_menu(hmenu: int, label: str = "menu") -> list[str]:
    """Debug: dump all menu item labels."""
    items = []
    count = user32.GetMenuItemCount(hmenu)
    for i in range(count):
        text = _get_menu_item_text(hmenu, i)
        items.append(text or f"(separator at {i})")
    return items


def play_floscript(script_path: str, timeout: float = 15) -> dict:
    """Trigger Macro > Play FloSCRIPT and feed it the script path.

    Uses Win32 menu API (WM_COMMAND) instead of keyboard — works from
    any process context as long as we're in the same desktop session.
    """
    # Step 1: Find main window
    hwnd = find_flotherm_window(timeout=10)

    # Step 2: Get menu bar and find Macro submenu
    hmenu = user32.GetMenu(hwnd)
    if not hmenu:
        return {"ok": False, "error": "No menu bar found on Flotherm window"}

    top_items = _dump_menu(hmenu, "menubar")

    macro_menu = _find_submenu(hmenu, "macro")
    if not macro_menu:
        return {
            "ok": False,
            "error": f"Macro menu not found. Menu items: {top_items}",
        }

    # Find "Play FloSCRIPT" in Macro submenu
    macro_items = _dump_menu(macro_menu, "macro")
    play_item = _find_menu_item(macro_menu, "play")
    if play_item is None:
        return {
            "ok": False,
            "error": f"Play FloSCRIPT not found in Macro menu. Items: {macro_items}",
        }

    position, cmd_id = play_item

    # Step 3: Send WM_COMMAND to trigger Play FloSCRIPT
    user32.PostMessageW(hwnd, WM_COMMAND, cmd_id, 0)
    time.sleep(1.5)

    # Step 4: Find the file dialog
    try:
        dialog = find_dialog("Play FloSCRIPT", timeout=timeout)
    except RuntimeError:
        try:
            dialog = find_dialog("Open", timeout=3)
        except RuntimeError:
            # List visible windows for debugging
            visible = []
            for w in _enum_windows():
                if user32.IsWindowVisible(w):
                    t = _get_window_text(w)
                    if t:
                        visible.append(t)
            return {
                "ok": False,
                "error": f"File dialog not found. Visible windows: {visible[:10]}",
            }

    # Step 5: Set filename in the edit control (ID 1148)
    edit = user32.GetDlgItem(dialog, 1148)
    if not edit:
        return {"ok": False, "error": "Cannot find filename edit control (1148)"}

    path_buf = ctypes.create_unicode_buffer(script_path)
    user32.SendMessageW(edit, WM_SETTEXT, 0, path_buf)
    time.sleep(0.3)

    # Step 6: Click Open button (ID 1 = IDOK)
    open_btn = user32.GetDlgItem(dialog, 1)
    if not open_btn:
        return {"ok": False, "error": "Cannot find Open button"}

    user32.SendMessageW(open_btn, BM_CLICK, 0, 0)

    return {
        "ok": True,
        "menu_items": top_items,
        "macro_items": macro_items,
        "cmd_id": cmd_id,
    }
