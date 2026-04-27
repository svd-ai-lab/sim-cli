---
name: workbench-sim
description: Use when driving Ansys Workbench via PyWorkbench SDK (ansys-workbench-core) or RunWB2 batch journals — project creation, analysis system management, IronPython journal execution, file transfer, and sub-solver (PyMechanical/PyFluent/PySherlock) integration through sim runtime.
---

# workbench-sim

You are connected to **Ansys Workbench** via sim-cli. This file is the
**index**. It tells you where to look for actual content — it does not
contain the content itself.

The `/connect` response told you which active layers apply via:

```json
"skills": {
  "root":               "<sim-skills>/workbench",
  "active_sdk_layer":   "0.4",
  "active_solver_layer": "24.1"
}
```

Always read the index for `base/`, then your active `sdk/<version>/`,
then your active `solver/<version>/`. Later layers override earlier
ones on identically-named files.

---

## base/ — always relevant

Concepts, API patterns, and version-agnostic reference:

| Path | What's there |
|---|---|
| `base/reference/pyworkbench_api.md` | PyWorkbench SDK API surface: `launch_workbench`, `run_script_string`, `upload_file`, `download_file`, `start_mechanical_server`, `start_fluent_server`. **Read first.** |
| `base/reference/journal_scripting.md` | IronPython `.wbjn` scripting reference: `SetScriptVersion`, `GetTemplate`, `CreateSystem`, `GetContainer`, and the result file convention. |
| `base/reference/system_templates.md` | Available analysis system templates: Static Structural, Modal, Thermal, Fluent, CFX, etc. |
| `base/reference/file_transfer.md` | File upload/download patterns between client and server. |
| `base/reference/sub_solver_integration.md` | Starting PyMechanical, PyFluent, PySherlock servers from within a Workbench session. |
| `base/snippets/` | Numbered IronPython journal snippets (01 through 05). Each writes results to `%TEMP%/sim_wb_result.json`. |
| `base/examples/` | Official PyWorkbench examples from pyansys.com — Fluent workflow, PyMechanical integration, logging, cooled turbine blade, cyclic symmetry, axisymmetric rotor, material designer. |
| `base/workflows/static_structural/` | **6-step Static Structural walkthrough** (Engineering Data → Geometry → Model → Setup → Solution → Results). Per-cell API reference + gotchas + executable `walk_workflow.py`. |
| `base/known_issues.md` | Vendor quirks, SDK version constraints, IronPython limitations. |

## sdk/<active_sdk_layer>/ — PyWorkbench SDK specifics

- `sdk/0.4/` — Minimum SDK for Ansys 24.1.
  - `notes.md` — `release` parameter (not `version`), missing methods vs 0.10+.
- `sdk/0.10/` — Modern SDK (requires Ansys >= 24.2).
  - `notes.md` — New APIs (`download_project_archive`, `stop_*_server`), version gate.

## solver/<active_solver_layer>/ — Ansys release specifics

- `solver/24.1/` — Ansys 2024 R1.
  - `notes.md` — IronPython .NET 4.x constraints, SDK 0.4-0.9 only.

---

## Hard constraints (apply to every session)

1. **Never call `launch_workbench()` from a snippet.** sim-cli already
   started the Workbench session. A second launch spawns a conflicting
   server process.
2. **All snippets are IronPython journals**, not Python SDK calls. The
   driver's `run()` method sends code through `run_script_string()` to
   the Workbench IronPython sandbox. Use Workbench API calls
   (`SetScriptVersion`, `GetTemplate`, etc.), not `ansys.workbench.core`.
3. **Results go through file convention.** IronPython stdout is not
   piped. Write JSON to `%TEMP%/sim_wb_result.json` for the driver to
   read back.
4. **Never invent Category A defaults.** Geometry, materials, BCs,
   acceptance criteria — if missing, ask the user.
5. **Acceptance ≠ exit code.** Validate against physics-based criteria
   (e.g., component count, temperature range), not just exit code.

---

## Required protocol (one paragraph)

After `/connect` succeeds: read `base/reference/pyworkbench_api.md` and
`base/reference/journal_scripting.md` to understand the execution model.
Gather Category A inputs from the user. Execute IronPython journals
incrementally via `sim exec`, checking `last.result` after every step.
Use snippets from `base/snippets/` adapted to the user's task. After the
final step, evaluate against the user's acceptance criteria. For the
canonical smoke test, the snippet sequence is `01_smoke_test` →
`02_create_static_structural`, followed by verifying 6 standard
components exist.
