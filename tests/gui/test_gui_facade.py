"""Unit tests for ``sim.gui.GuiController`` / ``SimWindow``.

Approach: monkeypatch ``sim.gui._pywinauto_tools._run_uia`` to return
canned responses so we exercise the facade without spawning real
pywinauto subprocesses (which would fail in CI anyway). This covers
the shape of the calls (hwnd/label flow-through) + the None-on-miss
contract of ``find``.
"""
from __future__ import annotations

import pytest

from sim.gui import GuiController, SimWindow
from sim.gui import _pywinauto_tools as tools


@pytest.fixture
def fake_tools(monkeypatch):
    """Patch the subprocess runner so each public helper returns a recorded dict."""
    calls: list[tuple[str, dict]] = []

    def _fake_run_uia(code, timeout_s=10.0):
        raise AssertionError("_run_uia should be bypassed in tests")

    monkeypatch.setattr(tools, "_run_uia", _fake_run_uia)

    def make_patch(fn_name, response):
        def _impl(*args, **kwargs):
            calls.append((fn_name, {"args": args, "kwargs": kwargs}))
            return response
        monkeypatch.setattr(tools, fn_name, _impl)
        return _impl

    monkeypatch.setattr(tools, "pywinauto_available", lambda: True)
    return {"calls": calls, "make": make_patch}


def test_available_proxies_to_module(monkeypatch):
    monkeypatch.setattr(tools, "pywinauto_available", lambda: True)
    ctrl = GuiController()
    assert ctrl.available is True
    monkeypatch.setattr(tools, "pywinauto_available", lambda: False)
    assert ctrl.available is False


def test_process_filter_preserved():
    filt = ("fluent", "cx", "cortex")
    ctrl = GuiController(process_name_substrings=filt)
    assert ctrl.process_filter == filt


def test_find_returns_none_on_miss(fake_tools):
    fake_tools["make"]("find_window", {"ok": True, "window": None})
    ctrl = GuiController(("comsol",))
    assert ctrl.find("nope", timeout_s=0.1) is None


def test_find_returns_none_when_subprocess_fails(fake_tools):
    fake_tools["make"]("find_window", {"ok": False, "error": "timeout"})
    ctrl = GuiController(("comsol",))
    assert ctrl.find("x") is None


def test_find_returns_simwindow_on_hit(fake_tools, tmp_path):
    fake_tools["make"]("find_window", {
        "ok": True,
        "window": {
            "hwnd": 12345, "pid": 9999, "proc": "comsol.exe",
            "title": "连接到 COMSOL", "rect": [10, 20, 600, 400],
        },
    })
    ctrl = GuiController(("comsol",), workdir=str(tmp_path))
    win = ctrl.find("连接到")
    assert isinstance(win, SimWindow)
    assert win.hwnd == 12345
    assert win.pid == 9999
    assert win.proc == "comsol.exe"
    assert win.title == "连接到 COMSOL"
    d = win.as_dict()
    assert d["hwnd"] == 12345 and d["rect"] == [10, 20, 600, 400]


def test_click_forwards_hwnd_and_label(fake_tools):
    fake_tools["make"]("click_by_name", {"ok": True, "clicked": "OK", "strategy": "button_by_title"})
    # Bypass find — construct a bare SimWindow directly
    from sim.gui import _WindowHandle
    w = SimWindow(_WindowHandle(hwnd=42, pid=1, proc="x", title="t", rect=None))
    result = w.click("OK")
    assert result == {"ok": True, "clicked": "OK", "strategy": "button_by_title"}
    assert fake_tools["calls"][-1][0] == "click_by_name"
    args = fake_tools["calls"][-1][1]
    assert args["args"][0] == 42
    assert args["args"][1] == "OK"


def test_send_text_passes_field(fake_tools):
    fake_tools["make"]("send_text", {"ok": True, "field": "Username"})
    from sim.gui import _WindowHandle
    w = SimWindow(_WindowHandle(hwnd=7, pid=1, proc="x", title="t", rect=None))
    r = w.send_text("alice", into="Username")
    assert r == {"ok": True, "field": "Username"}
    call = fake_tools["calls"][-1]
    assert call[0] == "send_text"
    assert call[1]["args"] == (7, "alice")
    assert call[1]["kwargs"]["field"] == "Username"


def test_close_and_activate_forward_hwnd(fake_tools):
    fake_tools["make"]("close_window", {"ok": True})
    fake_tools["make"]("activate_window", {"ok": True})
    from sim.gui import _WindowHandle
    w = SimWindow(_WindowHandle(hwnd=99, pid=1, proc="x", title="t", rect=None))
    assert w.close() == {"ok": True}
    assert w.activate() == {"ok": True}
    kinds = [c[0] for c in fake_tools["calls"]]
    assert "close_window" in kinds and "activate_window" in kinds


def test_screenshot_writes_under_workdir(monkeypatch, tmp_path):
    """screenshot() must land under <workdir>/screenshots/ and forward hwnd."""
    captured: dict = {}

    def _shot(hwnd, path):
        captured["hwnd"] = hwnd
        captured["path"] = path
        return {"ok": True, "path": path, "width": 800, "height": 600}

    monkeypatch.setattr(tools, "screenshot_window", _shot)

    from sim.gui import _WindowHandle
    w = SimWindow(
        _WindowHandle(hwnd=55, pid=1, proc="x", title="t", rect=None),
        workdir=str(tmp_path),
    )
    r = w.screenshot(label="login")
    assert r["ok"] is True
    assert captured["hwnd"] == 55
    assert str(tmp_path) in captured["path"]
    assert captured["path"].endswith(".png")
    # screenshots subdir should have been created
    assert (tmp_path / "screenshots").is_dir()


def test_list_and_snapshot_forward_filter(fake_tools):
    fake_tools["make"]("list_windows", {"ok": True, "windows": []})
    fake_tools["make"]("snapshot_uia_tree", {"ok": True, "windows": []})

    ctrl = GuiController(("fluent", "cx"))
    ctrl.list_windows()
    ctrl.snapshot(max_depth=2)

    seen = {c[0]: c[1] for c in fake_tools["calls"]}
    assert seen["list_windows"]["args"] == (("fluent", "cx"),)
    # snapshot passes process tuple positionally + max_depth kw
    assert seen["snapshot_uia_tree"]["args"][0] == ("fluent", "cx")
    assert seen["snapshot_uia_tree"]["kwargs"]["max_depth"] == 2


def test_pywinauto_available_off_windows(monkeypatch):
    """On non-Windows hosts pywinauto_available must return False without
    attempting to spawn a subprocess."""
    monkeypatch.setattr("os.name", "posix")
    # Force the module to re-evaluate
    assert tools.pywinauto_available() is False
