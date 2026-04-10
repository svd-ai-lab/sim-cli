"""Win32 GUI automation backend for Flotherm (Qt application).

Uses pywinauto with UIA backend to automate:
  Macro menu > Play FloSCRIPT > file dialog > script path

Runs inside the sim-server process (interactive desktop session required).
Flotherm uses Qt, so standard Win32 GetMenu() doesn't work — UIA is needed.
"""
from __future__ import annotations

import time


def play_floscript(script_path: str, timeout: float = 15) -> dict:
    """Trigger Macro > Play FloSCRIPT and feed it the script path.

    Uses pywinauto UIA backend for Qt menu automation.
    """
    try:
        from pywinauto import Desktop
    except ImportError:
        return {"ok": False, "error": "pywinauto not installed"}

    # Step 1: Find Flotherm window
    desktop = Desktop(backend="uia")
    try:
        flo_win = desktop.window(title_re=".*Simcenter Flotherm.*")
        flo_win.wait("visible", timeout=10)
    except Exception as e:
        return {"ok": False, "error": f"Flotherm window not found: {e}"}

    # Step 2: Click Macro menu
    try:
        menu_bar = flo_win.child_window(control_type="MenuBar", found_index=0)
        macro_item = menu_bar.child_window(title_re=".*Macro.*", control_type="MenuItem")
        macro_item.click_input()
        time.sleep(0.5)
    except Exception as e:
        # Try alternate: look for menu item directly
        try:
            macro_item = flo_win.child_window(title="Macro", control_type="MenuItem")
            macro_item.click_input()
            time.sleep(0.5)
        except Exception as e2:
            return {"ok": False, "error": f"Cannot find Macro menu: {e}, then {e2}"}

    # Step 3: Click "Play FloSCRIPT"
    try:
        play_item = desktop.window(control_type="MenuItem", title_re=".*Play FloSCRIPT.*")
        play_item.click_input()
        time.sleep(1.0)
    except Exception:
        try:
            play_item = desktop.window(control_type="MenuItem", title_re=".*Play.*")
            play_item.click_input()
            time.sleep(1.0)
        except Exception as e:
            return {"ok": False, "error": f"Cannot find Play FloSCRIPT menu item: {e}"}

    # Step 4: Handle file dialog
    try:
        dialog = desktop.window(title_re=".*Play FloSCRIPT.*|.*Open.*")
        dialog.wait("visible", timeout=timeout)

        # Try setting the filename via the edit/combo control
        try:
            edit = dialog.child_window(control_type="Edit", found_index=0)
            edit.set_text(script_path)
        except Exception:
            # Fallback: ComboBox
            combo = dialog.child_window(control_type="ComboBox", title_re=".*File name.*|.*文件名.*")
            edit = combo.child_window(control_type="Edit")
            edit.set_text(script_path)

        time.sleep(0.3)

        # Click Open/OK button
        try:
            open_btn = dialog.child_window(title_re="Open|打开|OK", control_type="Button")
            open_btn.click_input()
        except Exception:
            # Press Enter as fallback
            edit.type_keys("{ENTER}")

    except Exception as e:
        return {"ok": False, "error": f"File dialog interaction failed: {e}"}

    return {"ok": True, "method": "pywinauto_uia"}
