# Result extraction

There are two extraction modes: live Mechanical result objects via `uv run sim exec`,
and post-mortem `.rst` reads with DPF in normal CPython. Default to the
post-mortem DPF path when the solve already finished and the result file is on
disk; use the live path when you need to mutate or evaluate the current
Mechanical project.

## Adding result objects

Before you can query results, they must exist in the Solution tree:

```python
sol = Model.Analyses[0].Solution

td  = sol.AddTotalDeformation()
eqv = sol.AddEquivalentStress()
rf  = sol.AddForceReaction()

sol.EvaluateAllResults()   # compute everything
```

Before adding an unfamiliar result type, inspect
`mechanical.capabilities:analysis:<index>` and confirm the corresponding
`solution.Add...` method exists in `add_result_methods`.

If the solve is already done, `EvaluateAllResults()` is cheap — it
reads from the `.rst` and interpolates. Adding a new result after solve
triggers a re-read but NOT a re-solve.

## Reading scalar quantities

```python
td  = sol.Children[0]   # assuming it's the first result
max_def = td.Maximum    # Quantity object
min_def = td.Minimum

# Convert to float
max_val = max_def.Value           # raw float
max_unit = str(max_def.Unit)      # "m"
print(max_def.ToString())         # "0.00123 m"
```

Result objects expose: `.Minimum`, `.Maximum`, `.Average`,
`.MinimumOfMinimumOverTime`, `.MaximumOfMaximumOverTime`.

## Scoped results (by named selection)

```python
ns = [x for x in Model.NamedSelections.Children if x.Name == "critical_face"][0]

eqv = sol.AddEquivalentStress()
eqv.Location = ns
sol.EvaluateAllResults()

print("Max stress on critical_face:", eqv.Maximum.ToString())
```

## Exporting to CSV

```python
# Built-in export
eqv.ExportToTextFile(r"C:\work\max_stress.txt")

# Or data table for time-history
for v in eqv.TabularData.Values:
    print(v)
```

## .rst file access

```python
import os
rst_path = Model.Analyses[0].ResultFileName
print("Result file:", rst_path)
# Download to client for DPF processing
```

Then on the **client side** (not inside `run_python_script`):

```python
# From the sim host, grab the file
result = mech.download(files="*.rst", target_dir="C:/work/results")
print(result)
```

## Reading `.rst` on the agent side with PyDPF

For post-mortem result extraction (no live Mechanical session needed), use
`ansys-dpf-core` in normal CPython:

```python
from ansys.dpf import core as dpf

ds = dpf.DataSources("path/to/file.rst")
model = dpf.Model(ds)
disp = model.results.displacement().eval()
stress = model.results.stress().eval()
```

Pick this when: solve already finished, you only need to read results, and you
do not need to add new result objects.

Pick the live `uv run sim exec` path above when: you need to add a new result type,
evaluate scoped results against a NamedSelection that is not computed yet, or
the user wants the live Mechanical window to update.

## Common numbers cheat sheet

| Result | How to get max value |
|---|---|
| Total deformation | `sol.AddTotalDeformation().Maximum.Value` (m) |
| Equivalent (von-Mises) stress | `sol.AddEquivalentStress().Maximum.Value` (Pa) |
| Max principal stress | `sol.AddMaximumPrincipalStress().Maximum.Value` (Pa) |
| Safety factor (min) | `sol.AddSafetyFactor().Minimum.Value` |
| Reaction force on a fixed support | `sol.AddForceReaction(fs).YComponent.Value` (N) |

## Structured dump pattern

```python
import json

sol = Model.Analyses[0].Solution
sol.EvaluateAllResults()

result = {
    "status": str(sol.Status),
    "max_deformation_m": sol.Children[0].Maximum.Value if sol.Children else None,
    "children": [str(c.Name) for c in sol.Children],
}
json.dumps(result)
```
