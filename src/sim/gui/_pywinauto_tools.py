"""Pywinauto-based UIA helpers run in isolated subprocesses.

Why subprocess isolation?
  pywinauto's UIA backend uses COM under the hood. ``invoke()`` on a
  menu/button throws ``COMError`` and can pollute the COM apartment of
  the calling process. flotherm's driver proved this the hard way and
  solved it by spawning every UIA call as a one-shot ``python -c``
  subprocess. We reuse that pattern here for every cross-driver GUI
  action: main process stays clean, each call is stateless.

Design inspiration:
  * subprocess isolation + Windows file-dialog fallback: flotherm
    ``drivers/flotherm/_win32_backend.py``
  * tool catalog (find/click/type/close/screenshot/snapshot):
    sandraschi/pywinauto-mcp (MIT).
    https://github.com/sandraschi/pywinauto-mcp

We call pywinauto directly (already a dep on Windows) instead of
vendoring pywinauto-mcp's MCP-decorated wrappers — the MCP layer only
adds value when exposing tools over the MCP protocol, which sim does
not use.

Every public helper returns a JSON-serialisable dict with at minimum
``ok: bool``. Failures set ``ok=False`` + ``error: str`` — they do not
raise — so higher layers can decide whether to escalate.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap

# Default subprocess wall-clock per UIA call (seconds).
_DEFAULT_TIMEOUT = 10.0


def pywinauto_available() -> bool:
    """Return True iff a subprocess can ``import pywinauto``.

    We check via subprocess (not ``import pywinauto`` in-process) so we
    avoid importing pywinauto into sim serve's main process. Returns
    False off-Windows.
    """
    if os.name != "nt":
        return False
    try:
        r = subprocess.run(
            [sys.executable, "-c", "import pywinauto"],
            capture_output=True, timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return False


# ── subprocess runner ────────────────────────────────────────────────────────

def _run_uia(code: str, timeout_s: float = _DEFAULT_TIMEOUT) -> dict:
    """Run ``code`` as a ``python -c`` subprocess.

    The subprocess is expected to print exactly **one** line of JSON on
    stdout — its result dict. Any uncaught exception turns into
    ``{ok: false, error: "<stderr or message>"}``.
    """
    if os.name != "nt":
        return {"ok": False, "error": "pywinauto helpers require Windows"}

    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            timeout=timeout_s,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"UIA subprocess timed out after {timeout_s}s"}
    except Exception as exc:
        return {"ok": False, "error": f"UIA subprocess launch failed: {exc}"}

    if proc.returncode != 0:
        err = (proc.stderr or "").strip() or f"exit {proc.returncode}"
        return {"ok": False, "error": err, "stdout": (proc.stdout or "").strip()}

    # Parse last non-empty stdout line as JSON. Some pywinauto builds
    # occasionally emit noise on stdout that we ignore.
    lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
    if not lines:
        return {"ok": False, "error": "no stdout from UIA subprocess"}
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError:
        return {"ok": False, "error": f"UIA subprocess did not emit JSON: {lines[-1]!r}"}


# ── Templates ───────────────────────────────────────────────────────────────
#
# Each template expects a ``PARAMS`` JSON dict passed as the first arg to
# python (``python -c '<template>' <params-json>``). We pre-format the
# params inline to keep shell quoting simple.


def _render(template: str, params: dict) -> str:
    """Inject params dict + json + sys imports into a UIA subprocess script."""
    header = textwrap.dedent(f"""
        import io, json, sys, time
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        PARAMS = {json.dumps(params)}
        def _emit(d):
            print(json.dumps(d, ensure_ascii=False))
        try:
            from pywinauto import Desktop, Application
            from pywinauto.findwindows import ElementNotFoundError
        except Exception as e:
            _emit({{"ok": False, "error": f"pywinauto import failed: {{e}}"}})
            raise SystemExit(0)
    """).lstrip()
    return header + template


# ── public helpers ──────────────────────────────────────────────────────────

_LIST_WINDOWS_BODY = textwrap.dedent("""
    proc_sub = tuple(s.lower() for s in PARAMS.get('process_name_substrings') or ())
    out = []
    try:
        for w in Desktop(backend='uia').windows():
            try:
                if not w.is_visible():
                    continue
                title = w.window_text() or ''
                try:
                    pid = w.process_id()
                except Exception:
                    pid = 0
                try:
                    import psutil
                    try:
                        proc_name = psutil.Process(pid).name()
                    except Exception:
                        proc_name = ''
                except Exception:
                    proc_name = ''
                if proc_sub:
                    if not any(s in proc_name.lower() for s in proc_sub):
                        continue
                try:
                    r = w.rectangle()
                    rect = [r.left, r.top, r.right, r.bottom]
                except Exception:
                    rect = None
                out.append({'hwnd': w.handle, 'pid': pid, 'proc': proc_name, 'title': title, 'rect': rect})
            except Exception:
                continue
    except Exception as e:
        _emit({'ok': False, 'error': f'list_windows: {e}'})
        raise SystemExit(0)
    _emit({'ok': True, 'windows': out})
""")


def list_windows(process_name_substrings: tuple[str, ...] = ()) -> dict:
    """Return visible top-level windows, optionally filtered by process name."""
    return _run_uia(_render(_LIST_WINDOWS_BODY, {
        "process_name_substrings": list(process_name_substrings),
    }))


_FIND_WINDOW_BODY = textwrap.dedent("""
    title_sub = PARAMS.get('title_contains') or ''
    proc_sub = tuple(s.lower() for s in PARAMS.get('process_name_substrings') or ())
    deadline = time.monotonic() + float(PARAMS.get('timeout_s', 5))
    match = None
    while time.monotonic() < deadline and match is None:
        try:
            for w in Desktop(backend='uia').windows():
                try:
                    if not w.is_visible():
                        continue
                    title = w.window_text() or ''
                    if title_sub and title_sub not in title:
                        continue
                    try:
                        pid = w.process_id()
                    except Exception:
                        pid = 0
                    proc_name = ''
                    try:
                        import psutil
                        proc_name = psutil.Process(pid).name() if pid else ''
                    except Exception:
                        proc_name = ''
                    if proc_sub and not any(s in proc_name.lower() for s in proc_sub):
                        continue
                    try:
                        r = w.rectangle()
                        rect = [r.left, r.top, r.right, r.bottom]
                    except Exception:
                        rect = None
                    match = {'hwnd': w.handle, 'pid': pid, 'proc': proc_name, 'title': title, 'rect': rect}
                    break
                except Exception:
                    continue
        except Exception:
            pass
        if match is None:
            time.sleep(0.3)
    if match is None:
        _emit({'ok': True, 'window': None})
    else:
        _emit({'ok': True, 'window': match})
""")


def find_window(
    title_contains: str = "",
    process_name_substrings: tuple[str, ...] = (),
    timeout_s: float = 5.0,
) -> dict:
    """Poll until a visible window with matching title+process is found, or timeout."""
    return _run_uia(_render(_FIND_WINDOW_BODY, {
        "title_contains": title_contains,
        "process_name_substrings": list(process_name_substrings),
        "timeout_s": float(timeout_s),
    }), timeout_s=float(timeout_s) + 5)


_CLICK_BODY = textwrap.dedent("""
    hwnd = int(PARAMS['hwnd'])
    label = PARAMS['label']
    timeout_s = float(PARAMS.get('timeout_s', 5))
    try:
        app = Application(backend='uia').connect(handle=hwnd)
        win = app.window(handle=hwnd)
    except Exception as e:
        _emit({'ok': False, 'error': f'connect(handle={hwnd}) failed: {e}'})
        raise SystemExit(0)
    # try button by label first
    try:
        btn = win.child_window(title=label, control_type='Button')
        btn.wait('visible', timeout=timeout_s)
        btn.invoke() if hasattr(btn, 'invoke') else btn.click_input()
        _emit({'ok': True, 'clicked': label, 'strategy': 'button_by_title'})
        raise SystemExit(0)
    except SystemExit:
        raise
    except Exception:
        pass
    # fallback: any control whose name matches
    try:
        ctl = win.child_window(title=label)
        ctl.wait('visible', timeout=timeout_s)
        ctl.click_input()
        _emit({'ok': True, 'clicked': label, 'strategy': 'any_control_by_title'})
        raise SystemExit(0)
    except SystemExit:
        raise
    except Exception as e:
        _emit({'ok': False, 'error': f'no control titled {label!r} in hwnd={hwnd}: {e}'})
""")


def click_by_name(hwnd: int, label: str, timeout_s: float = 5.0) -> dict:
    """Click the control titled ``label`` inside the window ``hwnd``."""
    return _run_uia(_render(_CLICK_BODY, {
        "hwnd": int(hwnd),
        "label": label,
        "timeout_s": float(timeout_s),
    }), timeout_s=float(timeout_s) + 5)


_SEND_TEXT_BODY = textwrap.dedent("""
    hwnd = int(PARAMS['hwnd'])
    text = PARAMS['text']
    field = PARAMS.get('field') or ''
    timeout_s = float(PARAMS.get('timeout_s', 5))
    try:
        app = Application(backend='uia').connect(handle=hwnd)
        win = app.window(handle=hwnd)
    except Exception as e:
        _emit({'ok': False, 'error': f'connect failed: {e}'})
        raise SystemExit(0)
    try:
        if field:
            edit = win.child_window(title=field, control_type='Edit')
        else:
            # no field specified -> first editable control
            edit = win.child_window(control_type='Edit', found_index=0)
        edit.wait('visible', timeout=timeout_s)
        try:
            edit.set_edit_text(text)
        except Exception:
            edit.type_keys(text, with_spaces=True, with_tabs=True, with_newlines=True)
        _emit({'ok': True, 'field': field or '<first_edit>'})
    except Exception as e:
        _emit({'ok': False, 'error': f'send_text failed: {e}'})
""")


def send_text(hwnd: int, text: str, field: str = "", timeout_s: float = 5.0) -> dict:
    """Type ``text`` into an Edit control, optionally matching by accessible name."""
    return _run_uia(_render(_SEND_TEXT_BODY, {
        "hwnd": int(hwnd),
        "text": text,
        "field": field,
        "timeout_s": float(timeout_s),
    }), timeout_s=float(timeout_s) + 5)


_CLOSE_BODY = textwrap.dedent("""
    hwnd = int(PARAMS['hwnd'])
    try:
        app = Application(backend='uia').connect(handle=hwnd)
        app.window(handle=hwnd).close()
        _emit({'ok': True})
    except Exception as e:
        _emit({'ok': False, 'error': f'close failed: {e}'})
""")


def close_window(hwnd: int) -> dict:
    """Close the window ``hwnd`` (semantically equivalent to Alt+F4)."""
    return _run_uia(_render(_CLOSE_BODY, {"hwnd": int(hwnd)}))


_ACTIVATE_BODY = textwrap.dedent("""
    hwnd = int(PARAMS['hwnd'])
    try:
        app = Application(backend='uia').connect(handle=hwnd)
        win = app.window(handle=hwnd)
        win.set_focus()
        _emit({'ok': True})
    except Exception as e:
        _emit({'ok': False, 'error': f'activate failed: {e}'})
""")


def activate_window(hwnd: int) -> dict:
    """Bring ``hwnd`` to the foreground."""
    return _run_uia(_render(_ACTIVATE_BODY, {"hwnd": int(hwnd)}))


_SCREENSHOT_BODY = textwrap.dedent("""
    hwnd = int(PARAMS['hwnd'])
    out_path = PARAMS['out_path']
    try:
        app = Application(backend='uia').connect(handle=hwnd)
        win = app.window(handle=hwnd)
        img = win.capture_as_image()
        img.save(out_path, 'PNG')
        _emit({'ok': True, 'path': out_path, 'width': img.width, 'height': img.height})
    except Exception as e:
        _emit({'ok': False, 'error': f'screenshot failed: {e}'})
""")


def screenshot_window(hwnd: int, out_path: str) -> dict:
    """Capture ``hwnd`` (window-only, not full desktop) to ``out_path`` as PNG."""
    return _run_uia(_render(_SCREENSHOT_BODY, {
        "hwnd": int(hwnd),
        "out_path": str(out_path),
    }))


_SNAPSHOT_BODY = textwrap.dedent("""
    proc_sub = tuple(s.lower() for s in PARAMS.get('process_name_substrings') or ())
    max_depth = int(PARAMS.get('max_depth', 3))
    windows_out = []
    try:
        for w in Desktop(backend='uia').windows():
            try:
                if not w.is_visible():
                    continue
                try:
                    pid = w.process_id()
                except Exception:
                    pid = 0
                proc_name = ''
                try:
                    import psutil
                    proc_name = psutil.Process(pid).name() if pid else ''
                except Exception:
                    proc_name = ''
                if proc_sub and not any(s in proc_name.lower() for s in proc_sub):
                    continue
                def walk(el, depth):
                    if depth > max_depth:
                        return []
                    kids = []
                    try:
                        for c in el.children():
                            try:
                                info = {
                                    'name': c.window_text() or '',
                                    'control_type': c.element_info.control_type or '',
                                    'handle': c.handle or 0,
                                }
                                sub = walk(c, depth + 1)
                                if sub:
                                    info['children'] = sub
                                kids.append(info)
                            except Exception:
                                continue
                    except Exception:
                        pass
                    return kids
                windows_out.append({
                    'hwnd': w.handle,
                    'pid': pid,
                    'proc': proc_name,
                    'title': w.window_text() or '',
                    'controls': walk(w, 1),
                })
            except Exception:
                continue
    except Exception as e:
        _emit({'ok': False, 'error': f'snapshot: {e}'})
        raise SystemExit(0)
    _emit({'ok': True, 'windows': windows_out})
""")


def snapshot_uia_tree(
    process_name_substrings: tuple[str, ...] = (),
    max_depth: int = 3,
) -> dict:
    """Return the UIA tree of every matching window down to ``max_depth``."""
    return _run_uia(_render(_SNAPSHOT_BODY, {
        "process_name_substrings": list(process_name_substrings),
        "max_depth": int(max_depth),
    }), timeout_s=30.0)


# ── util ────────────────────────────────────────────────────────────────────

def workdir_screenshot_path(workdir: str | os.PathLike, label: str) -> str:
    """Build a PNG path under ``<workdir>/screenshots/`` ensuring the dir exists.

    Not pywinauto-specific but kept here because ``SimWindow.screenshot`` is
    the sole user.
    """
    base = os.path.join(str(workdir), "screenshots")
    os.makedirs(base, exist_ok=True)
    # sanitise label for filesystem safety
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in label)[:64] or "shot"
    fd, path = tempfile.mkstemp(prefix=f"{safe}_", suffix=".png", dir=base)
    os.close(fd)
    return path
