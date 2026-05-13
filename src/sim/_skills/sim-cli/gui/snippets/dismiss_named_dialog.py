"""Dismiss a blocking dialog by title and button text.

Paste into ``sim exec`` when the plugin-specific skill identifies a
known modal dialog. Keep solver-specific titles in the plugin skill;
this shared snippet only shows the generic control flow.
"""

# ruff: noqa: F821
# This snippet is executed inside `sim exec`, where the runtime injects `gui`.

title = "Dialog title substring"
button = "OK"

dlg = gui.find(title_contains=title, timeout_s=5)
if dlg is None:
    _result = {"ok": False, "dismissed": False, "error": "dialog not visible"}
else:
    click = dlg.click(button, timeout_s=5)
    _result = {"ok": bool(click.get("ok")), "dismissed": bool(click.get("ok")), "click": click}
