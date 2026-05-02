"""Submit Java Shell code to a resolved COMSOL Desktop target."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

from .audit import append_audit
from .shell import JavaShellChannel


class SubmitError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def to_dict(self) -> dict:
        return {"ok": False, "status": self.code, "error": self.message}


def validate_guardrail(code: str, *, allow_arbitrary_java: bool = False) -> None:
    """Apply the MVP Java Shell guardrail."""

    if allow_arbitrary_java:
        return
    for lineno, line in enumerate(code.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("//") or stripped.startswith("#"):
            continue
        if stripped.startswith("model."):
            continue
        raise SubmitError(
            "guardrail_rejected",
            f"Line {lineno} is outside the MVP allowlist; use allow_arbitrary_java to submit it.",
        )


def _run_submit_subprocess(
    channel: JavaShellChannel,
    code_path: Path,
    *,
    submit_key: str = "run_button",
    timeout_s: float = 15,
) -> dict:
    if os.name != "nt":
        return {"ok": False, "status": "uia_unavailable", "error": "Desktop attach requires Windows"}

    params = {
        "hwnd": channel.target.hwnd,
        "input_handle": channel.input_handle,
        "code_path": str(code_path),
        "submit_key": submit_key,
    }
    script = textwrap.dedent(
        """
        import ctypes
        import json
        import sys
        import time
        from pathlib import Path

        PARAMS = json.loads(sys.argv[1])

        def emit(payload):
            print(json.dumps(payload, ensure_ascii=True))

        try:
            from pywinauto import Application, mouse
            from pywinauto.keyboard import send_keys
        except Exception as exc:
            emit({"ok": False, "status": "uia_unavailable", "error": f"pywinauto import failed: {exc}"})
            raise SystemExit(0)

        CF_UNICODETEXT = 13
        GMEM_MOVEABLE = 0x0002
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.GetClipboardData.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        ctypes.memmove.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]

        def get_clipboard_text():
            if not user32.OpenClipboard(None):
                return None
            try:
                handle = user32.GetClipboardData(CF_UNICODETEXT)
                if not handle:
                    return ""
                ptr = kernel32.GlobalLock(handle)
                if not ptr:
                    return ""
                try:
                    return ctypes.wstring_at(ptr)
                finally:
                    kernel32.GlobalUnlock(handle)
            finally:
                user32.CloseClipboard()

        def set_clipboard_text(text):
            data = text.encode("utf-16-le") + b"\\x00\\x00"
            buf = ctypes.create_string_buffer(data)
            if not user32.OpenClipboard(None):
                raise RuntimeError("OpenClipboard failed")
            try:
                user32.EmptyClipboard()
                handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
                if not handle:
                    raise RuntimeError("GlobalAlloc failed")
                ptr = kernel32.GlobalLock(handle)
                if not ptr:
                    raise RuntimeError("GlobalLock failed")
                try:
                    ctypes.memmove(ptr, ctypes.addressof(buf), len(data))
                finally:
                    kernel32.GlobalUnlock(handle)
                if not user32.SetClipboardData(CF_UNICODETEXT, handle):
                    raise RuntimeError("SetClipboardData failed")
            finally:
                user32.CloseClipboard()

        def find_shell_input(win):
            syntax_editors = []
            edit_controls = []
            try:
                descendants = win.descendants()
            except Exception:
                descendants = []
            for control in descendants:
                try:
                    ctype = control.element_info.control_type or ""
                    class_name = getattr(control.element_info, "class_name", "") or ""
                    name = control.window_text() or ""
                except Exception:
                    continue
                if ctype == "Edit" and class_name == "SyntaxEditor":
                    syntax_editors.append(control)
                elif ctype == "Edit" and ("input" in name.lower() or "command" in name.lower()):
                    edit_controls.append(control)
                elif ctype == "Edit":
                    edit_controls.append(control)
            if syntax_editors:
                return syntax_editors[-1]
            if edit_controls:
                return edit_controls[-1]
            return None

        try:
            code = Path(PARAMS["code_path"]).read_text(encoding="utf-8")
            app = Application(backend="uia").connect(handle=int(PARAMS["hwnd"]))
            win = app.window(handle=int(PARAMS["hwnd"]))
            win.set_focus()
            target = find_shell_input(win)
            if target is None:
                emit({"ok": False, "status": "input_not_found", "error": "No Java Shell SyntaxEditor/Edit input was found."})
                raise SystemExit(0)
            try:
                target.click_input()
            except Exception:
                try:
                    target.set_focus()
                except Exception:
                    pass
            old_clipboard = get_clipboard_text()
            set_clipboard_text(code)
            send_keys("^a")
            send_keys("^v")
            key = PARAMS.get("submit_key") or "ctrl_enter"
            if key in {"run_button", "button"}:
                rect = target.rectangle()
                x = max(rect.left - 14, 0)
                y = rect.top + max(int(rect.height() / 2), 1)
                mouse.click(button="left", coords=(x, y))
            elif key in {"ctrl_enter", "ctrl+enter"}:
                send_keys("^{ENTER}")
            elif key == "enter":
                send_keys("{ENTER}")
            else:
                emit({"ok": False, "status": "submit_failed", "error": f"unknown submit_key={key!r}"})
                raise SystemExit(0)
            time.sleep(0.2)
            if old_clipboard is not None:
                try:
                    set_clipboard_text(old_clipboard)
                except Exception:
                    pass
            emit({"ok": True, "status": "submitted", "verification": "verification_unavailable"})
        except Exception as exc:
            emit({"ok": False, "status": "submit_failed", "error": str(exc)})
        """
    ).strip()
    try:
        proc = subprocess.run(
            [sys.executable, "-c", script, json.dumps(params)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "status": "submit_failed", "error": f"submit timed out after {timeout_s}s"}
    if proc.returncode != 0:
        return {
            "ok": False,
            "status": "submit_failed",
            "error": (proc.stderr or "").strip() or f"submit subprocess exited {proc.returncode}",
        }
    lines = [line for line in (proc.stdout or "").splitlines() if line.strip()]
    if not lines:
        return {"ok": False, "status": "submit_failed", "error": "submit subprocess emitted no JSON"}
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError:
        return {"ok": False, "status": "submit_failed", "error": f"invalid submit JSON: {lines[-1]!r}"}


def submit_code(
    channel: JavaShellChannel,
    code: str,
    *,
    allow_arbitrary_java: bool = False,
    submit_key: str = "run_button",
    audit_dir: str | Path | None = None,
    timeout_s: float = 15,
) -> dict:
    """Submit Java Shell code through UIA and append an audit record."""

    validate_guardrail(code, allow_arbitrary_java=allow_arbitrary_java)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".java", delete=False) as fh:
        fh.write(code)
        code_path = Path(fh.name)
    try:
        result = _run_submit_subprocess(
            channel,
            code_path,
            submit_key=submit_key,
            timeout_s=timeout_s,
        )
    finally:
        try:
            code_path.unlink()
        except OSError:
            pass

    audit_path = append_audit(
        channel,
        code,
        str(result.get("status") or ("submitted" if result.get("ok") else "submit_failed")),
        audit_dir=audit_dir,
    )
    result["audit_log"] = str(audit_path)
    result["exec_language"] = "java-shell"
    result["target"] = channel.target.to_dict()
    return result
