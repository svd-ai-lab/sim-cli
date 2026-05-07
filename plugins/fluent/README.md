# sim-plugin-fluent

Ansys Fluent plugin for `sim`, built on PyFluent. It provides a live-session
driver, Fluent-focused inspect targets, artifact classification, and a bundled
agent skill for choosing between live sim sessions, direct PyFluent scripts,
and file-side artifact review.

## Install

```bash
uv pip install sim-plugin-fluent
```

Check that sim can discover Fluent:

```bash
sim check fluent
```

## Live Session Quickstart

```bash
sim connect --solver fluent --mode solver --ui-mode no_gui \
  --driver-option dimension=3 \
  --driver-option precision=double \
  --driver-option processor_count=2

sim inspect session.versions
sim inspect session.health
sim inspect fluent.files

sim exec --label smoke --code "_result = {'status': 'ok'}"
sim inspect last.result
sim disconnect
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
