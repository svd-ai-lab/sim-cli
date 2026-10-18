# sim-plugin-fluent

Ansys Fluent plugin for `sim`, built on PyFluent. It provides a live-session
driver, Fluent-focused inspect targets, artifact classification, and a bundled
agent skill for choosing between live sim sessions, direct PyFluent scripts,
and file-side artifact review.

## Install

For agent projects, install sim-cli-core and the Fluent plugin in the project
environment:

```powershell
uv init  # only if this is not already a uv project
uv add sim-cli-core sim-plugin-fluent
uv run sim plugin sync-skills --target .agents/skills --copy
uv run sim check fluent
uv run sim plugin doctor fluent --deep
```

For Claude Code, sync the bundled skill to `.claude/skills` instead:

```powershell
uv run sim plugin sync-skills --target .claude/skills --copy
```

`uv run sim ...` runs sim from this project environment, so it sees this
project's plugins. Without uv, create and activate a venv, then install
`sim-cli-core` plus this plugin with `python -m pip`.

## Live Session Quickstart

```powershell
uv run sim connect --solver fluent --mode solver --ui-mode no_gui `
  --driver-option dimension=3 `
  --driver-option precision=double `
  --driver-option processor_count=2

uv run sim inspect session.versions
uv run sim inspect session.health
uv run sim inspect fluent.files

uv run sim exec --label smoke --code "_result = {'status': 'ok'}"
uv run sim inspect last.result
uv run sim disconnect
```

## Direct PyFluent Quickstart

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

## Inspect Targets

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

## Compatibility

The plugin supports PyFluent `>=0.37,<0.39`. See
[`src/sim_plugin_fluent/compatibility.yaml`](src/sim_plugin_fluent/compatibility.yaml)
for the solver and SDK profile matrix.
