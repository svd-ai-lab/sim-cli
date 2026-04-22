"""L1 unit tests — GUI probes (GuiDialogProbe + ScreenshotProbe).

These do NOT launch Fluent — they only exercise the probes against mocks
or the local desktop. Full real-Fluent GUI validation lives in the
integration_fluent_mixing_elbow.py script.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


def _ctx(**kw):
    from sim.inspect import InspectCtx

    defaults = dict(
        stdout="", stderr="", workdir=tempfile.gettempdir(),
        wall_time_s=0.0, exit_code=0, driver_name="fluent", session_ns={},
    )
    defaults.update(kw)
    return InspectCtx(**defaults)


# ── ScreenshotProbe (per-window capture, no full-screen) ───────────────────────


def test_screenshot_probe_emits_no_window_when_nothing_matches(tmp_path):
    pytest.importorskip("PIL")
    pytest.importorskip("pywinauto")
    from sim.inspect import ScreenshotProbe

    # Use a substring that matches NO process on this host
    p = ScreenshotProbe(
        filename_prefix="test",
        process_name_substrings=("this_process_does_not_exist_xyz__",),
    )
    ctx = _ctx(workdir=str(tmp_path))
    result = p.probe(ctx)

    # Must NOT produce an artifact (no full-screen fallback)
    assert result.artifacts == []
    # Must emit exactly one info diag explaining no window matched
    codes = [d.code for d in result.diagnostics]
    assert "sim.screenshot.no_window" in codes
    # And nothing gets written to workdir
    shots_dir = Path(tmp_path) / "screenshots"
    assert not shots_dir.exists() or not any(shots_dir.iterdir())


def test_screenshot_probe_captures_real_window_if_one_matches(tmp_path):
    """If a process named 'explorer.exe' has a visible window, we can capture it."""
    pytest.importorskip("PIL")
    pytest.importorskip("pywinauto")
    from sim.inspect import ScreenshotProbe

    p = ScreenshotProbe(
        filename_prefix="test",
        process_name_substrings=("explorer",),  # almost always present on Windows
    )
    ctx = _ctx(workdir=str(tmp_path))
    result = p.probe(ctx)

    if not result.artifacts:
        # Some CI hosts have explorer.exe w/ no visible windows. Acceptable.
        codes = [d.code for d in result.diagnostics]
        assert "sim.screenshot.no_window" in codes or "sim.inspect.screenshot_bad_rect" in codes
        return

    art = result.artifacts[0]
    assert Path(art.path).is_file()
    assert art.role == "screenshot"
    assert art.size is not None and art.size > 0
    # info diag present
    assert any(d.code == "sim.screenshot.captured" for d in result.diagnostics)


def test_screenshot_probe_handles_bad_workdir():
    from sim.inspect import ScreenshotProbe

    # Point at an impossible path AND a matching process hint; probe must not raise
    p = ScreenshotProbe(process_name_substrings=("explorer",))
    ctx = _ctx(workdir="Z:\\impossible\\does\\not\\exist\\shots")
    result = p.probe(ctx)
    # Either workdir creation fails (warning) or no window matched (info)
    codes = [d.code for d in result.diagnostics]
    assert any(c.startswith("sim.inspect.screenshot") or c == "sim.screenshot.no_window"
               for c in codes)


# ── GuiDialogProbe behavior ────────────────────────────────────────────────────


def test_gui_dialog_probe_applies_on_windows():
    """pywinauto importable → applies() must be True."""
    pytest.importorskip("pywinauto")
    from sim.inspect import GuiDialogProbe

    p = GuiDialogProbe()
    assert p.applies(_ctx()) is True


def test_gui_dialog_probe_returns_probe_result():
    """Running against an empty desktop shouldn't crash — returns an
    empty-ish ProbeResult. If there are incidental fluent/ansys windows
    on this host, that's fine (the probe exists to surface them)."""
    pytest.importorskip("pywinauto")
    from sim.inspect import GuiDialogProbe, ProbeResult

    p = GuiDialogProbe()
    result = p.probe(_ctx())
    assert isinstance(result, ProbeResult)
    # Every diag we emit must at least have a source starting with "gui:"
    for d in result.diagnostics:
        assert d.source.startswith("gui:"), f"unexpected source: {d.source!r}"


def test_gui_dialog_probe_filter_narrows_processes():
    """Filtering by process name 'nonexistent_xyz' should return zero
    dialog-like entries (probe still emits gracefully)."""
    pytest.importorskip("pywinauto")
    from sim.inspect import GuiDialogProbe

    p = GuiDialogProbe(process_name_substrings=("nonexistent_process_xyz__",))
    result = p.probe(_ctx())
    # No process matches → no dialog-like diags
    dialogs = [d for d in result.diagnostics if d.code == "fluent.gui.dialog_detected"]
    assert dialogs == []


# ── Channel 8a — 3-level severity classification (Plan C) ─────────────────────
#
# After Phase 2 L3 surfaced a Chinese COMSOL login dialog and Boss challenged
# the underlying design ("agent 本来就能读懂中文，为啥做文字匹配?"), we
# changed tack:
#
#   - Probe ONLY prefixes strong unambiguous error signal words (English,
#     the de-facto programming convention for "hard failure" text).
#   - Everything else is severity=info with the full title + screenshot
#     attached so the agent can use its LLM to judge.
#   - We do NOT maintain Chinese/French/Japanese/... keyword lists —
#     that's the agent's job via LLM, not ours via string matching.
#
# Strong error hints: error / fatal / abort / failed / crash / exception
# Strong warning hint: warning (only)
# All other windows: info + neutral code=window_observed


def _classify(probe, title: str) -> tuple[str, str]:
    """Duplicate of the probe's internal classify logic so the test can
    hit it without needing pywinauto wiring. Returns (severity, code_suffix)."""
    low = title.lower()
    if any(h in low for h in probe._ERROR_SIGNAL_HINTS):
        return "error", "dialog_with_error_signal"
    if any(h in low for h in probe._WARNING_SIGNAL_HINTS):
        return "warning", "dialog_with_warning_signal"
    return "info", "window_observed"


@pytest.mark.parametrize("title,expected_severity", [
    # ── Strong error signals (should escalate to severity=error) ─────
    ("An Error Occurred",                  "error"),
    ("Fatal exception in solver",          "error"),
    ("Abort: cannot continue",             "error"),
    ("Operation Failed",                   "error"),
    ("The program has crashed",            "error"),
    ("Unhandled Exception",                "error"),
    # ── Warning signal (escalate to warning only) ────────────────────
    ("Warning: disk space low",            "warning"),
    # ── Everything else → info (agent reads title + screenshot itself) ─
    # Chinese dialog titles — NOT escalated anymore. Agent's LLM reads
    # them natively; the probe only reports "I saw window X".
    ("连接到 COMSOL Multiphysics Server",  "info"),
    ("登录",                                "info"),
    ("请等待应用程序",                       "info"),
    ("错误",                                "info"),   # ← see note below
    ("警告: 磁盘空间",                       "info"),
    ("确认关闭",                            "info"),
    # Plain main windows — always info
    ("mixing_elbow - Ansys Fluent",        "info"),
    ("heating_circuit.mph - COMSOL Multiphysics", "info"),
    ("Notepad",                             "info"),
])
def test_gui_dialog_three_level_severity(title, expected_severity):
    """Plan C: probe only makes a severity call on English strong-signal
    words. Localized titles stay info; agent reads them via LLM.

    Note on '错误' (Chinese for 'error'): even though semantically it's
    an error, the probe intentionally DOES NOT flag it — because once
    we accept "do non-English", we own a hopeless multilingual keyword
    table. The agent's LLM can flag it at near-zero cost after reading
    the structured info-level diag.
    """
    from sim.inspect import GuiDialogProbe

    p = GuiDialogProbe()
    severity, code_suffix = _classify(p, title)
    assert severity == expected_severity, (
        f"title {title!r}: expected severity={expected_severity!r}, "
        f"got {severity!r} (code_suffix={code_suffix!r})"
    )


def test_gui_dialog_error_hints_minimal_and_english_only():
    """Regression guard: don't re-add multilingual hints."""
    from sim.inspect import GuiDialogProbe

    p = GuiDialogProbe()
    assert p._ERROR_SIGNAL_HINTS == (
        "error", "fatal", "abort", "failed", "crash", "exception",
    )
    assert p._WARNING_SIGNAL_HINTS == ("warning",)
    # No _DIALOG_HINTS attribute — the old Plan-A tuple is gone.
    assert not hasattr(p, "_DIALOG_HINTS"), (
        "Plan A's _DIALOG_HINTS should be removed; probe now uses "
        "_ERROR_SIGNAL_HINTS + _WARNING_SIGNAL_HINTS"
    )
