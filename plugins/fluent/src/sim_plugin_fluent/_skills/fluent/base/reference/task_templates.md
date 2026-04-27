# Task Templates — fluent-sim v0

> Each template defines: goal, required inputs, common missing items, runtime step order, and completion condition.
> These are **task-level protocols**, not Python code. For API details, see `pyfluent_cheat_sheet.md` (planned).

---

## Template 1 — Watertight Geometry Meshing

### Goal
Generate a volume mesh from a closed (watertight) geometry file using the PyFluent Watertight Geometry workflow. Optionally switch to solver at the end.

### Required Inputs

| Input | Type | Must ask if missing |
|---|---|---|
| Geometry file path | `.pmdb`, `.scdoc`, or `.stl` | YES |
| Length unit | `in`, `m`, `mm`, etc. | YES |
| Max surface mesh size | Float | YES |
| Volume fill type | `poly-hexcore`, `tet`, etc. | YES |
| Max hex cell length | Float (if poly-hexcore) | YES |
| Switch to solver after mesh? | Bool | YES |

### Common Missing Items
- Length unit (users often forget; wrong unit silently produces wrong-scale mesh)
- Volume fill parameters (poly-hexcore requires `HexMaxCellLength`)
- Whether boundary layers are needed and with which transition type

### Runtime Step Order

| Step | Label | Notes |
|---|---|---|
| 1 | `connect` | mode=meshing |
| 2 | `init-import-geometry` | InitializeWorkflow + ImportGeometry |
| 3 | `add-local-sizing` | Can use defaults; note if skipping customization |
| 4 | `surface-mesh` | Set MaxSize |
| 5 | `describe-geometry` | SetupType must match geometry (fluid-only vs. with voids) |
| 6 | `update-boundaries-regions` | UpdateBoundaries + UpdateRegions |
| 7 | `boundary-layers` | Required for wall-bounded flows; skippable for inviscid |
| 8 | `volume-mesh` | Set VolumeFill + HexMaxCellLength |
| 9 | `switch-to-solver` | Optional; required if solver workflow follows immediately |

### Completion Condition
- `run_count` = number of completed steps (typically 7–8 before switch-to-solver)
- `last.result.result.volume_mesh_done = true`
- If switching: `last.result.result.switch_to_solver_done = true`
- Cell count visible in stdout of volume-mesh step (extract and report)

---

## Template 2 — Fault-Tolerant Meshing

### Goal
Generate a volume mesh from a geometry that may have gaps, overlaps, or non-manifold edges using the Fault-Tolerant Meshing workflow.

### Required Inputs

| Input | Type | Must ask if missing |
|---|---|---|
| Geometry file path | `.fmd` (preferred), `.stl`, etc. | YES |
| Number of enclose fluid regions | Integer | YES — drives later task count |
| Number of identify regions steps | Integer | YES |
| Target cell size / mesh controls | Float or defaults | YES |
| Part management: one-zone-per policy | `part`, `body`, `face` | Ask if non-default |

### Common Missing Items
- Number of enclose/identify region steps (variable; wrong count breaks task sequence)
- Whether `ObjectSetting['DefaultObjectSetting']` exists in the target Fluent version (version-dependent; wrap in try/except)

### Runtime Step Order

| Step | Label | Notes |
|---|---|---|
| 1 | `connect` | mode=meshing |
| 2 | `init-import-cad` | ImportCADAndPart, set file path |
| 3 | `part-management` | ObjectSetting.OneZonePer; wrap in try/except for version compat |
| 4 | `init-ft-workflow` | InitializeWorkflow(WorkflowType='Fault-tolerant Meshing') |
| 5–8 | `enclose-fluid-<N>` | One step per enclose region (count from required inputs) |
| 9 | `create-regions` | CreateRegions |
| 10–11 | `identify-region-<N>` | One step per identify step |
| 12 | `define-leakage` | Optional; ask user |
| 13 | `update-regions` | |
| 14 | `add-boundary-layers` | Optional |
| 15 | `generate-surface-mesh` | |
| 16 | `improve-surface-mesh` | Optional |
| 17 | `generate-volume-mesh` | |
| 18 | `switch-to-solver` | Optional |

### Completion Condition
- `run_count` matches actual steps executed
- `last.result.result.volume_mesh_done = true`
- Cell count in stdout (extract and report)
- No `LookupError` exceptions in any step's stderr

---

## Template 3 — Solver Run

### Goal
Load an existing case (+data), run N iterations, and extract a specified quantity (e.g., mass flow rate, pressure drop, residuals).

### Required Inputs

| Input | Type | Must ask if missing |
|---|---|---|
| Case file path | `.cas.h5` or `.cas` | YES |
| Data file path | `.dat.h5` or `.dat` | YES |
| Number of iterations | Integer | YES |
| Quantity to extract | e.g., mass flow rate at outlet | YES — determines final step |
| Outlet/inlet boundary names | String | YES — required for report definitions |

### Common Missing Items
- Boundary names (must match names in the case file exactly; case-sensitive)
- Whether a data file exists or only a case file (data file = initialized field; case only = needs initialization)
- Convergence threshold (if user wants convergence-based stop vs. fixed iteration count)

### Runtime Step Order

| Step | Label | Notes |
|---|---|---|
| 1 | `connect` | mode=solver |
| 2 | `read-case-data` | read_case + read_data; verify files exist before sending |
| 3 | `mesh-check` | Always run; surface in stdout |
| 4 | `run-iterations` | `iterate(iter_count=N)`; may take minutes; CMD_TIMEOUT_S=600 |
| 5 | `extract-<quantity>` | Define report_definition, call compute(); label by quantity name |

### Completion Condition
- `run_count = 3` after iterations (read-case-data, mesh-check, run-iterations)
- `last.result.result.iterations_run = N`
- Extracted quantity present in `last.result.result`
- Quantity value reported explicitly (not "see stdout")

---

## Template 4 — Smoke / Connectivity Test

### Goal
Verify that the sim runtime is correctly configured and can start a Fluent session, execute a trivial snippet, and disconnect cleanly. Used for environment validation, not simulation.

### Required Inputs
- None required from user. All defaults acceptable.

### Runtime Step Order

| Step | Label | Notes |
|---|---|---|
| 1 | `connect` | mode=solver, no_gui, processors=2 |
| 2 | `smoke-snippet` | `_result = {'status': 'ok', 'test': 'smoke'}` |
| 3 | `disconnect` | |

### Completion Condition
- `session.summary.connected = true` after connect
- `last.result.ok = true` after snippet
- `disconnect` exits 0
- No exceptions anywhere

---

## Notes on Template Selection

- If the user says "mesh the geometry", ask which workflow type (watertight vs. fault-tolerant) — do not guess from file extension alone.
- If the user says "run the simulation", ask whether a case file already exists or whether meshing must be done first.
- Templates may be chained (meshing → solver) but must remain in separate sessions unless `switch_to_solver()` is used within a meshing session.
- **Reference example values are for API syntax illustration only.** Parameter values in `reference/pyfluent_examples/` (e.g., 0.4 m/s, 293.15 K, `water-liquid` from the mixing elbow example) describe a specific published test case. They must not be used to fill in missing user inputs. When required inputs are absent, apply SKILL.md §5.1: ask for Category A inputs — do not substitute example values.
