# Observation commands and Mechanical

This doc is the **contract** between sim's observation commands and the
Mechanical session. Read this before using `sim inspect` or
`sim screenshot` against a running Mechanical.

## The coupling

sim has four observation primitives:

| sim command | HTTP route | What it touches |
|---|---|---|
| `sim inspect session.summary` | `GET /inspect/session.summary` | Driver metadata (local, no SDK call). |
| `sim inspect last.result` | `GET /inspect/last.result` | Last `run_python_script` return value, cached in `_state.runs[-1]`. |
| `sim exec '<code>'` | `POST /exec` | Forwarded to `MechanicalDriver.run` → `mechanical.run_python_script(code)`. |
| `sim screenshot -o shot.png` | `GET /screenshot` | `PIL.ImageGrab.grab()` of the sim-serve host desktop. |

For these to work **coherently**, two invariants must hold:

### Invariant 1: SDK state and GUI state are the same state

`run_python_script` mutates the in-memory model of the running Mechanical
process. That process owns the GUI window. Therefore any state change you
make via `exec` is **immediately visible** in the window — Mechanical
repaints within one frame. So:

```bash
sim exec "Model.Analyses[0].AddFixedSupport()"
sim screenshot -o after.png        # the Tree now shows "Fixed Support"
```

This invariant is **broken** if you launch embedded (`pm.App()`) — the
embedded interpreter has no window. sim's driver refuses embedded mode
for exactly this reason. Never pass `batch=True` unless you also accept
that `sim screenshot` will only show an empty desktop.

### Invariant 2: `inspect` sees the same SDK the driver is talking to

`session.summary` is local metadata — it does not round-trip. It reports
what the driver thinks is true:

```json
{
  "session_id": "...",
  "mode": "mechanical",
  "ui_mode": "gui",
  "backend": "pymechanical",
  "batch": false,
  "run_count": 7,
  "version": "24.1"
}
```

If `batch` is ever `true`, the screenshot path is broken and you should
tell the caller immediately.

## How to use observation, practically

### Pattern A: snapshot before + after

```bash
sim screenshot -o before.png
sim exec "Model.Analyses[0].AddPressure()"
sim screenshot -o after.png
```

Diff the two to confirm the Tree changed. This is the canonical proof
that a scripting call "took".

### Pattern B: structured inspect via `exec` + JSON

```bash
sim exec '
import json
result = {
    "analyses": len(Model.Analyses),
    "bodies":   len([b for b in Model.Geometry.GetChildren(DataModelObjectCategory.Body, True)]),
    "mesh_nodes": Model.Mesh.Nodes,
}
json.dumps(result)
'
sim inspect last.result
```

`last.result` will contain the parsed JSON. This is the **preferred way
to query model state** — it's structured, it's cached, and it round-trips
through the SDK so you know the session is alive.

### Pattern C: verify via product_info

`session.summary` does not call the SDK. If you need to prove the gRPC
channel is still alive **without** running a snippet, use the driver's
`query("mechanical.product_info")` path (exposed as the HTTP
`GET /inspect/mechanical.product_info` once the server is wired for
Mechanical).

## When observation lies

1. **During a long solve**. `Solve(True)` blocks until done. While it
   runs, the GUI updates a progress bar but `exec` is also blocked.
   `screenshot` still works (it goes through a separate HTTP handler,
   not the gRPC channel).

2. **After a crash**. If Mechanical segfaults, the gRPC channel dies but
   `session.summary` still says `connected: true` (because it's local
   metadata). Always do one `exec "1"` to confirm before trusting the
   summary.

3. **Modal dialogs**. If Mechanical pops a modal dialog (e.g. a license
   prompt, an "are you sure?" on delete), `run_python_script` blocks
   until the dialog is dismissed. sim's `screenshot` can capture the
   dialog — use it to recover.

## Driver → server → client flow

```
┌──────────┐  HTTP   ┌────────────┐  gRPC   ┌──────────────────┐
│ sim CLI  │ ──────► │ sim serve  │ ──────► │ AnsysWBU.exe     │
│ exec/    │         │ + Driver   │         │ (Mechanical GUI) │
│ inspect  │ ◄────── │            │ ◄────── │                  │
│ screen-  │         │            │         └──────────────────┘
│ shot     │         │            │
└──────────┘         │ ImageGrab  │──── PIL grabs desktop bitmap
                     │ (PIL)      │     where the GUI window lives
                     └────────────┘
```

The `ImageGrab` path and the gRPC path are **independent**, which is why
screenshot still works even when `exec` is blocked. Use this asymmetry
to diagnose hangs.
