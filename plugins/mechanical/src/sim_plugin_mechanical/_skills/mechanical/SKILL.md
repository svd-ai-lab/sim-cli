---
name: mechanical-sim
description: Use when driving Ansys Mechanical via PyMechanical (ansys-mechanical-core) through the sim runtime, or reading solved `.rst` files with DPF on the agent side. Covers boundary conditions, loads, solver execution, and result extraction. This is the physics-layer counterpart to workbench-sim (which orchestrates cells 1-3); mechanical-sim owns cells 4-6 of the Static Structural workflow. Observation commands (sim screenshot / inspect) are tightly coupled with both the PyMechanical gRPC client *and* the Mechanical.exe GUI window — always launch with `batch=False` so the window is on the desktop for live sessions.
---

# mechanical-sim

This file is the **Ansys Mechanical** index. Use DPF for solved `.rst` files
on disk; use sim-cli/PyMechanical for live Mechanical sessions that mutate,
solve, inspect, or update the GUI-backed project.

This is **not** the Abaqus plugin. Do not run Abaqus `.inp` decks or
Abaqus/CAE scripts here. Use `solver=abaqus` for Dassault SIMULIA Abaqus;
use `solver=mechanical` only for Ansys Mechanical / PyMechanical sessions.

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
   `batch=False`** — so the driver defaults to GUI mode. Confirm both
   `ui_mode == "gui"` and `batch == false` from `inspect session.summary`
   before relying on screenshots for GUI sync.

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
| `base/workflows/model_review_loop.md` | Required checkpoint loop: inspect health, project identity, model summary, then run one bounded snippet. |
| `base/workflows/debug_failed_exec.md` | Failure triage loop for scoping, selections, mesh, solve, and result extraction failures. |
| `base/workflows/workbench_handoff.md` | Workbench-to-Mechanical checklist for Static Structural workflows. |
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
5. **Never trust raw names or paths as public evidence.** Return counts,
   booleans, self-created ASCII tags, or sanitized strings from snippets.

## Required protocol

If the user's question is about an existing solved project (a `.rst` on
disk), use DPF on the agent side; do not launch Mechanical at all.

Before every Mechanical script:

1. Read `base/workflows/model_review_loop.md` and inspect
   `session.health`, `mechanical.project.identity`, and
   `mechanical.model.summary`.
2. Check `base/known_issues.md` for the operation you are about to do.
3. If this is a Workbench handoff, read `base/workflows/workbench_handoff.md`
   and confirm Mechanical sees the expected analysis and non-empty geometry.
4. Run one bounded snippet, ending with `json.dumps(...)`.
5. Inspect `last.result` and `mechanical.model.summary`. In GUI mode, use a
   screenshot as visual confirmation after significant tree changes.
6. If execution fails, switch to `base/workflows/debug_failed_exec.md` before
   trying another full script.
