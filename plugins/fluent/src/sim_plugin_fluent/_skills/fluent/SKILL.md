---
name: fluent-sim
description: Use when working with Ansys Fluent through live sim sessions, direct PyFluent scripts, or file-side artifact review.
---

# fluent-sim

This skill is the Fluent-specific operating guide. Choose the control path
that fits the task, then load only the references needed for that path.

## Choose The Control Path

| Path | Best for | Starting point |
|---|---|---|
| Live sim session | Stateful edits, GUI observation, incremental solver work, remote Windows diagnostics, version probes, and inspecting a running Fluent session | `uv run sim connect --solver fluent --mode <solver|meshing> --ui-mode <gui|no_gui>` |
| Direct PyFluent script | Deterministic batch runs, reproducible examples, CI-friendly smoke scripts, and workflows that can own their process lifecycle | `from ansys.fluent.core import launch_fluent` in a normal Python script |
| File-side artifact review | Case/data/mesh inventory, transcript tails, CSV/PNG/PDF outputs, and offline checks that do not need a live solver | Use Python file readers, text inspection, and Fluent artifact helpers before opening a session |

Use sim when the task needs a persistent runtime or live observation. Use a
direct PyFluent script when a one-shot batch program is clearer. Use file-side
helpers when the question is about artifacts already on disk.

## Live Sim Session

After connecting, inspect:

```bash
uv run sim inspect session.versions
uv run sim inspect session.health
uv run sim inspect session.summary
```

The `session.versions` payload selects the active overlays. Always read
`base/`, then the active `sdk/<active_sdk_layer>/`, then the active
`solver/<active_solver_layer>/` when present. Later layers override earlier
files with the same name.

Expected SDK layer directories are:

- `sdk/0.38/` for PyFluent 0.38.x
- `sdk/0.37/` for PyFluent 0.37.x

Useful live inspect targets:

- `session.summary`
- `session.health`
- `session.versions`
- `last.result`
- `workflow.summary`
- `field.catalog` / `fluent.field.catalog`
- `fluent.models.summary`
- `fluent.boundaries.summary`
- `fluent.case.summary`
- `fluent.mesh.summary`
- `fluent.files`

Use `uv run sim exec` snippets with the injected `session`, `solver`, or `meshing`
object. Keep snippets small enough that `last.result` can prove the current
state before the next step.

## Direct PyFluent Script

For direct scripts, own the launch and teardown explicitly:

```python
from ansys.fluent.core import launch_fluent

solver = launch_fluent(mode="solver", ui_mode="no_gui", precision="double")
try:
    solver.settings.file.read_case(file_name="case.cas.h5")
    solver.solution.initialization.hybrid_initialize()
    solver.solution.run_calculation.iterate(iter_count=10)
finally:
    solver.exit()
```

This path is a good fit when the result can be produced in one deterministic
program and you do not need a live agent-visible session between steps.

For direct PyFluent scripts, launch the session normally with PyFluent and do
not rely on sim-injected variables.

## Long-running execution and recovery

Keep bounded Fluent work in the foreground when it fits the active tool-call
budget. Use a native journal, direct PyFluent script, or background process only
when the solve is expected to outlive that budget, must continue across agent
turns, or the user explicitly asks for background execution. Keep live sessions
for incremental setup and inspection; use a settled script or journal for a
repeatable long solve.

For a long run, use absolute transcript/log and case/data output paths so the
agent can inspect progress and results later. Do not require a fixed directory
tree, a job manifest, or sim-cli when the direct Fluent or PyFluent path is
sufficient.

A shell or tool timeout ends that observation call; it does not prove Fluent
stopped. Before retrying or stopping, check the Fluent/PyFluent process,
transcript tail, monitor output, and case/data timestamps. Confirm process
ownership from the executable, full command line, start time, and working or
output paths. Never terminate every `fluent`, `ansys`, or `cortex` process
by name.

Use *resume* only when a usable `.cas/.dat(.h5)` pair, autosave, or another
Fluent-native checkpoint can actually continue the calculation. Without one,
describe the action as a restart rather than promising generic resume behavior.
Keep direct PyFluent scripts responsible for their own launch and teardown.

## File-Side Artifact Review

Before launching Fluent, inventory what is already present:

- `.cas` / `.cas.h5`: case setup
- `.dat` / `.dat.h5`: solution data
- `.msh` / `.msh.h5`: mesh input
- `.trn` / `.jou`: transcript and journal evidence
- `.pdf` / `.fla`: flamelet and PDF table artifacts
- `.csv` / `.png` / `.json`: exported reports, figures, and structured output

Use this path for quick triage, output extraction, and deciding whether a live
session is necessary.

## Layered References

| Path | Use |
|---|---|
| `base/reference/task_templates.md` | Required inputs and workflow step order |
| `base/reference/runtime_patterns.md` | Fluent dependency chains and state ordering |
| `base/reference/acceptance_checklists.md` | Completion checks for bundled workflows |
| `base/reference/api_discovery.md` | `dir()` and `child_names` patterns for renamed APIs |
| `base/reference/tui_vs_settings.md` | When to prefer Settings API or TUI |
| `base/reference/pyfluent_overview.md` | Quick PyFluent orientation |
| `base/snippets/` | Reusable live-session snippets |
| `base/workflows/` | Longer workflow examples |
| `sdk/0.38/` | PyFluent 0.38.x docs and examples |
| `sdk/0.37/` | PyFluent 0.37.x compatibility notes |
| `solver/25.2/` | Fluent 25.2-specific notes |
| `doc-search/` | Local Fluent documentation search helper |

For PyFluent API questions, start with the active `sdk/` overlay. For Fluent
physics, meshing, UDF, or solver-model questions, use `doc-search/` against the
local Ansys documentation tree rather than guessing names or defaults.

## Live Sim Session Constraints

These constraints apply only after sim has already created a live Fluent
session:

1. Do not call `pyfluent.launch_fluent()` inside a `uv run sim exec` snippet. Use the
   injected `session`, `solver`, or `meshing` object.
2. Do not switch between meshing and solver mode by assumption. The mode is
   selected at connect time unless a Fluent workflow explicitly returns a
   solver object.
3. Confirm each stateful step before sending the next dependent step. Fluent
   meshing and solver workflows are order-sensitive.
4. Use GUI actuation only for surfaces the SDK cannot reach. Prefer
   `solver.settings.*`, `session.tui.*`, and `meshing.workflow.*` for
   reproducible work.

## Flamelet And PDF Table Workflows

For partially premixed steady-diffusion flamelet workflows, load:

- `base/reference/task_templates.md` - Template 5
- `base/reference/runtime_patterns.md` - staged flamelet/PDF dependency chain
- `base/reference/acceptance_checklists.md` - Checklist 5
- `base/snippets/setup_partially_premixed_flamelet.py`
- `base/snippets/write_pdf_table.py`
- `base/snippets/read_case_pdf_data.py`
- `base/snippets/inspect_reacting_bc_scalars.py`

Short version: import CHEMKIN as `flamelet-mixture`, generate flamelets and the
PDF table, persist the table with `write_pdf_cmd(...)`, and restart or
postprocess with `read_case -> read_pdf -> read_data`.
