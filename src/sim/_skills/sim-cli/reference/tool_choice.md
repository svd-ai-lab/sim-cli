# Tool choice

sim-cli is the right tool when the task needs a live solver session, vendor-only Python inside the solver, GUI actuation, runtime version probing, or Windows-friendly streaming diagnostics. For post-mortem artifact reads and small acceptance computations, prefer the file-side Python path when it is closer to the data.

Keep both paths visible when both are valid. Pick the one that matches the state the user actually has.

## Example 1: read an Abaqus `.sta` after a job

| Mode | Pick when | Recipe |
|---|---|---|
| Live | The solve is in progress or an Abaqus session is already open. | `sim inspect job.diagnostics` |
| Post-mortem | The job finished and `job.sta` is on disk. | Prefer `uv run python -c "from pathlib import Path; print(Path('job.sta').read_text(errors='replace'))"` when uv is available; otherwise use the user's Python environment. |

## Example 2: read a Mechanical `.rst`

| Mode | Pick when | Recipe |
|---|---|---|
| Live | Mechanical is open and you need to add/evaluate result objects in the Solution tree. | `sim exec` with IronPython, for example `sol.Children[0].Maximum.Value` |
| Post-mortem | The solve already finished and you only need result data from the file. | Use `ansys-dpf-core` in normal CPython against the downloaded `.rst`. |

```python
from ansys.dpf import core as dpf

ds = dpf.DataSources("file.rst")
model = dpf.Model(ds)
disp = model.results.displacement().eval()
stress = model.results.stress().eval()
```

## Example 3: introspect a saved COMSOL `.mph`

| Mode | Pick when | Recipe |
|---|---|---|
| Live | The model needs to be mutated, solved, or compared against the live JPype session. | `sim inspect comsol.model.describe_text` |
| Post-mortem | The question is about a saved `.mph`: parameters, physics tags, solved/unsolved state, mesh size. | `from sim_plugin_comsol.lib import inspect_mph; inspect_mph(path)` |
