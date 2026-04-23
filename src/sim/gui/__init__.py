"""``sim.gui`` — cross-driver GUI actuation.

``GuiController`` is the object that each session-capable driver
injects into your ``sim exec`` namespace as ``gui``. It is an
**actuation** layer — meaning the probes (``sim.inspect``) only
observe and this module only acts. The decision of whether to act
and how lives one layer higher, in the LLM agent that issues
``sim exec`` commands.

Usage from an agent::

    # Find a blocking dialog and click OK
    dlg = gui.find(title_contains='Login', timeout_s=5)
    if dlg:
        dlg.click('OK')

    # Fill a text field, then click OK
    dlg = gui.find(title_contains='File Save')
    dlg.send_text('/tmp/out.cas.h5', into='File name')
    dlg.click('OK')

    # Full UIA tree of everything the solver currently has on screen
    state = gui.snapshot()

Remote use is identical — the same object lives in the namespace of a
``sim serve`` running on the remote Windows host; the agent just talks
to it over ``sim exec --host <remote>``.

All calls return JSON-serialisable dicts. Errors are surfaced via
``ok=False`` + ``error`` (from ``_pywinauto_tools``) — methods do not
raise unless the caller passes invalid Python types. The agent's
subsequent inspect round (channel #3 traceback / #8 window_observed)
will reflect the outcome.

See ``sim-skills/sim-cli/gui/SKILL.md`` for the full agent-facing
reference and solver-specific dialog recipes.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from sim.gui import _pywinauto_tools as _tools


@dataclass
class _WindowHandle:
    """Lightweight handle describing a window found by :class:`GuiController`."""
    hwnd: int
    pid: int
    proc: str
    title: str
    rect: list[int] | None


class SimWindow:
    """A found window. All methods proxy to pywinauto subprocess helpers.

    Instances are produced by :meth:`GuiController.find` — do not
    construct directly unless you already know the hwnd.

    Every method returns a dict with at least ``ok: bool``. On failure
    ``error`` is populated. Agents should read ``ok`` before chaining.
    """

    def __init__(self, handle: _WindowHandle, workdir: str | os.PathLike | None = None):
        self._h = handle
        self._workdir = workdir or os.getcwd()

    # ── accessors ────────────────────────────────────────────────────────
    @property
    def hwnd(self) -> int:
        return self._h.hwnd

    @property
    def title(self) -> str:
        return self._h.title

    @property
    def pid(self) -> int:
        return self._h.pid

    @property
    def proc(self) -> str:
        return self._h.proc

    def as_dict(self) -> dict:
        return {
            "hwnd": self._h.hwnd, "pid": self._h.pid, "proc": self._h.proc,
            "title": self._h.title, "rect": self._h.rect,
        }

    # ── actions ──────────────────────────────────────────────────────────
    def click(self, button_label: str, timeout_s: float = 5.0) -> dict:
        """Click the control whose accessible name equals ``button_label``.

        Tries a Button control first, falls back to any control with that
        title. Returns ``{ok, clicked, strategy}`` on success or
        ``{ok: false, error}`` if the control was not found.
        """
        return _tools.click_by_name(self._h.hwnd, button_label, timeout_s=timeout_s)

    def send_text(self, text: str, into: str = "", timeout_s: float = 5.0) -> dict:
        """Type ``text`` into an Edit control. ``into`` is the field's
        accessible name; if empty, types into the first Edit in tab order.
        """
        return _tools.send_text(self._h.hwnd, text, field=into, timeout_s=timeout_s)

    def close(self) -> dict:
        """Close this window (WM_CLOSE / Alt+F4 equivalent)."""
        return _tools.close_window(self._h.hwnd)

    def activate(self) -> dict:
        """Bring this window to the foreground."""
        return _tools.activate_window(self._h.hwnd)

    def screenshot(self, label: str = "window") -> dict:
        """Save a PNG of this window (window-only, not the whole desktop).

        The file lands under ``<workdir>/screenshots/<label>_*.png``; the
        returned dict carries ``path`` so the agent can fetch / reference it.
        """
        out = _tools.workdir_screenshot_path(self._workdir, label)
        return _tools.screenshot_window(self._h.hwnd, out)

    def __repr__(self) -> str:
        return f"<SimWindow hwnd={self._h.hwnd} pid={self._h.pid} title={self._h.title!r}>"


class GuiController:
    """Per-driver GUI actuation facade.

    Construct with the process-name substrings that identify the driver's
    windows (e.g. ``('fluent', 'cx', 'cortex')``). Every ``find`` / ``list``
    call filters to those processes so accidental hits on the user's
    unrelated applications are avoided.

    ``available`` is ``False`` on non-Windows hosts or when pywinauto is
    not importable — agents should check this before driving GUI flows.
    Calling methods on an unavailable controller will return
    ``{ok: false, error: ...}`` rather than raise.
    """

    def __init__(
        self,
        process_name_substrings: tuple[str, ...] = (),
        workdir: str | os.PathLike | None = None,
    ):
        self._procs = tuple(process_name_substrings)
        self._workdir = workdir or os.getcwd()

    @property
    def available(self) -> bool:
        """True iff pywinauto is usable in this environment."""
        return _tools.pywinauto_available()

    @property
    def process_filter(self) -> tuple[str, ...]:
        return self._procs

    def list_windows(self) -> dict:
        """Return every visible top-level window owned by a matching process.

        Shape: ``{ok, windows: [{hwnd, pid, proc, title, rect}, ...]}``
        """
        return _tools.list_windows(self._procs)

    def find(self, title_contains: str = "", timeout_s: float = 5.0) -> "SimWindow | None":
        """Poll until a matching window appears, or return ``None`` on timeout.

        ``title_contains`` is a plain substring match (case-sensitive). Combine
        with this controller's process filter so you get exactly one intended
        window even if the user happens to have another app with the same title.
        """
        r = _tools.find_window(
            title_contains=title_contains,
            process_name_substrings=self._procs,
            timeout_s=timeout_s,
        )
        if not r.get("ok") or not r.get("window"):
            return None
        w = r["window"]
        return SimWindow(
            _WindowHandle(
                hwnd=int(w["hwnd"]), pid=int(w["pid"]),
                proc=str(w["proc"]), title=str(w["title"]),
                rect=w.get("rect"),
            ),
            workdir=self._workdir,
        )

    def wait_until_window_gone(
        self,
        title_contains: str,
        timeout_s: float = 30.0,
        poll_s: float = 0.5,
    ) -> bool:
        """Poll until no window with ``title_contains`` is visible, or timeout.

        Returns ``True`` if the window is gone before ``timeout_s``, ``False``
        if the timeout elapsed first.  Use this instead of ``time.sleep(N)``
        after dismissing a dialog — it returns as soon as the window closes
        rather than waiting a fixed duration.

        Example::

            dlg.click('OK')
            gui.wait_until_window_gone('Login', timeout_s=15)
        """
        import time as _t
        deadline = _t.monotonic() + timeout_s
        while _t.monotonic() < deadline:
            r = self.list_windows()
            titles = [w.get("title", "") for w in (r.get("windows") or [])]
            if not any(title_contains in t for t in titles):
                return True
            _t.sleep(poll_s)
        return False

    def snapshot(self, max_depth: int = 3) -> dict:
        """Full UIA tree dump of every matching window.

        Expensive; use for debugging or for agents that need to reason
        about the complete control tree. For targeted actions prefer
        :meth:`find` + :meth:`SimWindow.click`.
        """
        return _tools.snapshot_uia_tree(self._procs, max_depth=max_depth)


__all__ = ["GuiController", "SimWindow"]
