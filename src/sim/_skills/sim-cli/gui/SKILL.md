---
name: gui
description: Cross-driver GUI actuation for CAE solvers running under sim-cli. Use to click buttons, fill fields, dismiss dialogs, and capture window screenshots against GUI-capable driver windows through `sim exec`.
type: tool
---

# `gui` — cross-driver GUI actuation

Whenever the active driver runs with `ui_mode=gui` (or `desktop`),
`sim serve` injects a **`gui`** object into your `sim exec` namespace
alongside `session` / `solver` / `meshing` / `model`. The object is the
same shape across solvers — only the process filter differs — so one
skill serves every GUI-capable driver.

`/connect` advertises it:

```json
{
  "ok": true,
  "data": {
    "...": "...",
    "tools": ["gui"],
    "tool_refs": {"gui": "sim-cli/_skills/sim-cli/gui/SKILL.md"}
  }
}
```

If `tools` doesn't contain `"gui"`, the driver launched headless and
the object is absent — don't call it.

## When to reach for `gui`

Three scenarios dominate:

1. **A blocking dialog is wedging the workflow.** A login prompt,
   overwrite confirmation, or script-error dialog can pause agent work
   until someone clicks a button — that someone is you, via `gui`.
2. **You need to drive the GUI where the SDK can't.** Some workflows
   expose a UI-only surface that the driver API does not cover.
3. **You need a per-window screenshot.** `sim screenshot` captures the
   whole desktop. `SimWindow.screenshot()` captures just the window you
   care about — cheaper to read, less visual clutter for the LLM.

If the SDK has a programmatic path (`session.tui.*`, `model.solve()`,
`ModelUtil.loadCopy()`), prefer that. `gui` is for the UI-only surface
that the SDK doesn't cover.

## Remote equivalence

`gui` is in the session namespace on the `sim serve` side. You talk to
it via the existing `/exec` HTTP channel:

```bash
# local Windows box
sim exec "dlg = gui.find('Login'); dlg.click('OK')"

# Windows box on the LAN / Tailscale
sim --host 10.0.x.y exec "dlg = gui.find('Login'); dlg.click('OK')"
```

No new endpoint, no new protocol — the same API shape from anywhere
the agent runs.

Requirement on the server host: `sim serve` must run in a **real
interactive desktop session** (normal login or RDP). Windows
service / SSH session 0 has no desktop, so pywinauto can't enumerate
any windows even though the solver processes are running. This is the
same constraint GUI-capable drivers document.

## API

### Discover what the controller is looking at

```python
gui.available          # True iff pywinauto can run — check before driving anything
gui.process_filter     # tuple of process-name substrings this gui will target
gui.list_windows()     # {ok, windows: [{hwnd, pid, proc, title, rect}, ...]}
```

### Find a window (polled until timeout)

```python
dlg = gui.find(title_contains="Login", timeout_s=5)
# returns a SimWindow, or None on timeout
```

`title_contains` is a plain substring match (case-sensitive, any language).
Returns `None` if nothing matched — **always check** before calling
methods on it:

```python
dlg = gui.find("连接到")
if dlg is None:
    _result = {"ok": False, "error": "login dialog not visible"}
else:
    dlg.click("确定")
```

### Act on a window

Every action returns `{ok: bool, ...}`. No exceptions unless you pass
invalid Python types — surface `ok=False` + `error` to the agent.

```python
dlg.click("OK", timeout_s=5)             # click a button by accessible name
dlg.send_text("alice", into="Username")  # type into a named Edit field
dlg.send_text("/tmp/out.cas.h5")         # without `into` → first editable
dlg.close()                              # WM_CLOSE (Alt+F4 equivalent)
dlg.activate()                           # bring to foreground
dlg.screenshot(label="after_login")      # window-only PNG under workdir
```

Each action method tries the most natural pywinauto strategy first
(`button_by_title`) and falls back to a broader match
(`any_control_by_title`) before giving up — the response tells you
which path worked via the `strategy` field.

### Full UIA dump

Expensive but sometimes necessary for reasoning about an unfamiliar GUI:

```python
state = gui.snapshot(max_depth=3)
# {ok, windows: [{hwnd, pid, proc, title,
#                  controls: [{name, control_type, handle, children?}, ...]}]}
```

Use this when `find(title)` misses and you need to see what the GUI
actually exposes.

### Handle metadata

`SimWindow` fields you can read without another round-trip:

```python
dlg.hwnd     # int
dlg.pid      # int
dlg.proc     # str, process name
dlg.title    # current window title
dlg.as_dict() # {hwnd, pid, proc, title, rect}
```

## Typical patterns

### Pattern 1 — dismiss a blocking login dialog

```python
dlg = gui.find(title_contains="Login", timeout_s=5)
if dlg:
    dlg.send_text("alice", into="Username")
    dlg.send_text("secret", into="Password")
    dlg.click("OK")
_result = {"dismissed": dlg is not None}
```

### Pattern 2 — confirm a "file exists, overwrite?" dialog

```python
dlg = gui.find(title_contains="Question", timeout_s=3)
if dlg is None:
    dlg = gui.find(title_contains="overwrite", timeout_s=3)  # other
if dlg:
    dlg.click("OK")
_result = {"confirmed": dlg is not None, "title": dlg.title if dlg else None}
```

### Pattern 3 — walk the solver UI tree to find an unexpected control

```python
state = gui.snapshot(max_depth=4)
names = []
def walk(items):
    for c in items:
        if c.get("name"):
            names.append((c["control_type"], c["name"]))
        walk(c.get("children") or [])
for w in state["windows"]:
    walk(w.get("controls") or [])
_result = {"control_names": names[:50]}
```

### Pattern 4 — capture only the solver window for the agent to read

```python
dlg = gui.find(title_contains="Main", timeout_s=3)
if dlg:
    shot = dlg.screenshot(label="after_solve")
    _result = shot  # contains {ok, path, width, height}
else:
    _result = {"ok": False, "error": "main window not found"}
```

## Error handling

Every call returns a dict; failures look like
`{"ok": False, "error": "connect(handle=...) failed: ..."}`. The UIA
machinery runs in an isolated subprocess so a COM glitch in one call
never poisons the next.

Things that commonly make `ok` false:

| Symptom | Likely cause | What to do |
|---|---|---|
| `find` returns `None` | title didn't match / process filter too strict | print `gui.list_windows()` to see what is live |
| `click` says `no control titled ... in hwnd=...` | the button label in the UI is not what you think | snapshot the window, read `controls[*].name` |
| `screenshot` returns minimal PNG | window is minimized (pywinauto captures the window rect; min'd windows live at `(-32000, -32000, …)`) | `dlg.activate()` first, then screenshot |
| `gui.available` is `False` | off-Windows host, or pywinauto not installed | don't use `gui` — fall back to SDK-only path |
| `list_windows()` returns `[]` even though the solver clearly launched | `sim serve` was started from an SSH / non-interactive Windows session — the GUI exists in a session with no display surface and pywinauto can't see it | ask the operator to restart `sim serve` from a desktop session (RDP, Windows Terminal, or Task Scheduler with **"run only when user is logged on" + interactive**). See [`../SKILL.md` → "Where `sim serve` runs"](../SKILL.md). Do **not** retry. |
| `screenshot` returns a uniformly black PNG | same as above — non-interactive session has no compositor | same fix |

## Pitfalls

- **Don't guess button labels.** Windows localisation is real. Use
  `gui.snapshot()` to confirm the actual accessible name before calling
  `click(name)`.
- **Don't assume single window.** Some solvers open extra floating
  panels. `find(title)` returns the first match; if the workflow is
  ambiguous, use `list_windows()` and pick by `pid`.
- **Don't rely on `gui` for SDK-shaped work.** Solver objects (`session`,
  `model`) are always faster and more reliable than UI clicks. `gui` is
  the fallback for the UI-only surface.
- **Remote servers need a real desktop.** If `sim serve` runs from an
  SSH session, a Windows service, or any non-interactive context, the
  spawned solver process inherits a session with no display surface.
  pywinauto then finds zero windows, screenshots come back uniformly
  black, and `find(...)` silently times out — the server itself is up
  and reachable, only the GUI half is dead. Restart `sim serve` from a
  desktop session (Windows Terminal on the console, RDP, or Task
  Scheduler with "run only when user is logged on" + interactive). See
  [`../SKILL.md` → "Where `sim serve` runs"](../SKILL.md) for the full
  driver-by-driver matrix.

## Related skills

- Plugin-specific skills list the dialogs that a given driver is known
  to pop. Check those for recipes before inventing your own.
- `sim.inspect` probes (issue #8a `window_observed`, #8b screenshots)
  tell you **what is on screen** — read them first, then reach for
  `gui` to act.
