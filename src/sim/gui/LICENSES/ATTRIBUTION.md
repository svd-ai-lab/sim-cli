# Third-party attribution for `sim.gui`

`sim.gui` runs on the upstream **pywinauto** library (BSD-3), installed
as a dependency of sim-cli on Windows hosts. No pywinauto code is
vendored — we call the public API directly.

Design of the tool catalogue in `_pywinauto_tools.py` (find / click /
type / close / screenshot / snapshot) was informed by:

- [`sandraschi/pywinauto-mcp`](https://github.com/sandraschi/pywinauto-mcp)
  — MIT licensed. Their MCP-decorated wrappers showed which action set
  was worth exposing to LLM agents. We do not import or vendor their
  code; we re-implement directly over pywinauto because the MCP
  decoration layer is not useful outside an MCP server.

The subprocess-isolation pattern for UIA calls (one-shot
`python -c '...'` per action to keep the calling process's COM
apartment clean) is lifted from **this project's own**
`src/sim/drivers/flotherm/_win32_backend.py`, which proved it in
production against Simcenter Flotherm.

The Win32 ctypes file-dialog primitives in `_win32_dialog.py`
(`WM_SETTEXT` + `BM_CLICK` against control ids 1148 / 1) are also
extracted from that same flotherm backend so every driver can share the
implementation instead of copy-pasting it.
