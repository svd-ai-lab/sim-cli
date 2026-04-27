---
name: mechanical-sim
description: Use when driving Ansys Mechanical via PyMechanical (ansys-mechanical-core) through the sim runtime — boundary conditions, loads, solver execution, and result extraction. This is the physics-layer counterpart to workbench-sim (which orchestrates cells 1-3); mechanical-sim owns cells 4-6 of the Static Structural workflow. Observation commands (sim screenshot / inspect) are tightly coupled with both the PyMechanical gRPC client *and* the Mechanical.exe GUI window — always launch with `batch=False` so the window is on the desktop.
---

# mechanical-sim

You are connected to **Ansys Mechanical** via sim-cli. This file is the
**index**. It tells you where to look — it does not contain the content
itself.

The `/connect` response tells you which active layers apply:

```json
"skills": {
  "root":               "<sim-skills>/mechanical",
  "active_sdk_layer":   "0.12",
  "active_solver_layer": "24.1"
}
```

Always read `base/`, then your active `sdk/<version>/`, then your active
`solver/<version>/`. Later layers override earlier ones on identically-named
files.

---

## First principles

1. **Workbench orchestrates, Mechanical computes.** PyWorkbench drives
   Engineering Data / Geometry / Model. PyMechanical drives Setup /
   Solution / Results. Do not try to define boundary conditions via
   Workbench scripting — that belongs here.

2. **Observation is SDK+GUI coupled.** Every `sim exec` is a
   `mechanical.run_python_script(code)` call that mutates Mechanical's
   in-memory model. Mechanical's window on the desktop redraws after each
   call. Therefore `sim screenshot` (which grabs the desktop) always
   reflects the current SDK state. This coupling **only works with
   `batch=False`** — so the driver defaults to GUI mode and refuses to
   set `batch=True` unless the caller explicitly asks for `ui_mode=batch`.

3. **Scripts run inside Mechanical's IronPython interpreter.** Globals
   `ExtAPI`, `DataModel`, `Model`, `Quantity`, `Tree` are already
   available — do NOT `import ansys.mechanical`. The last expression's
   string form is what `run_python_script` returns, so end snippets with
   a `json.dumps(...)` literal to get structured output.

4. **`ExtAPI.DataModel.Project` is the root.** From there:
   `.Model` → the scene; `.Model.Analyses[0]` → the first analysis;
   `.Model.Geometry` → bodies; `.Model.Mesh` → meshing controls;
   `.Model.Materials` → material assignments.

---

## base/ — always relevant

| Path | What's there |
|---|---|
| `base/reference/pymechanical_api.md` | PyMechanical SDK surface: `launch_mechanical`, `run_python_script`, `download_project`, file transfer. **Read first.** |
| `base/reference/scripting_tree.md` | Mechanical's IronPython scripting tree: `ExtAPI`, `DataModel`, `Model`, `Tree`, common traversal patterns. |
| `base/reference/bc_scoping.md` | Boundary condition scoping: creating `Selection` objects, `NamedSelection`, face IDs, `ISelectionInfo`. This is the #1 source of errors. |
| `base/reference/solve_control.md` | Triggering solve (`analysis.Solve(True)`), monitoring state, reading solve messages. |
| `base/reference/result_extraction.md` | Traversing `analysis.Solution` to pull deformation/stress values, exporting to CSV, using `.rst` files. |
| `base/reference/observation_commands.md` | **How sim's observation commands couple with Mechanical.** Read this before using `sim inspect` / `sim screenshot` against a Mechanical session. |
| `base/snippets/` | Numbered snippets (01_smoke through 06_extract_results). Each ends with a `json.dumps(...)` literal for structured output. |
| `base/workflows/static_structural/` | End-to-end walk through cells 4-6, continuing where workbench-sim left off. |
| `base/known_issues.md` | Quirks: Chinese locale gRPC, batch-mode stdin, IronPython Unicode, `Selection` vs `ISelectionInfo`. |

## sdk/<active_sdk_layer>/

- `sdk/0.12/` — PyMechanical 0.12 (works with Ansys 24.1–25.2).
  - `notes.md` — `launch_mechanical(version=241, batch=False)`, `wait_till_mechanical_is_ready`.

## solver/<active_solver_layer>/

- `solver/24.1/` — Ansys Mechanical 24.1.
  - `notes.md` — scripting namespace: which `ExtAPI` members exist in 24.1.

---

## Hard constraints

1. **Never launch with `batch=True`** unless the user has explicitly
   asked for headless mode. sim's observation commands need the GUI.
2. **Never `import ansys.mechanical.*`** inside a snippet that goes
   through `run_python_script`. The interpreter is Mechanical's embedded
   IronPython — the Python SDK is the wrong side of the wire.
3. **Always end snippets with `json.dumps(...)`** to get structured
   stdout. `run_python_script` returns only the last expression's repr.
4. **Workbench skill owns cells 1-3.** If the user asks for geometry
   import or material definition, hand back to workbench-sim.

## Required protocol

Before every Mechanical script:

1. Call `/inspect session.summary` to confirm `ui_mode == "gui"` and
   `batch == False`.
2. Check `base/known_issues.md` for the operation you are about to do.
3. After the script runs, call `/screenshot` to confirm the visual state
   matches what the SDK reports.
