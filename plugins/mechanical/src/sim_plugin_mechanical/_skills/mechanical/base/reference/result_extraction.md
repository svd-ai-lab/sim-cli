# Result extraction

## Adding result objects

Before you can query results, they must exist in the Solution tree:

```python
sol = Model.Analyses[0].Solution

td  = sol.AddTotalDeformation()
eqv = sol.AddEquivalentStress()
rf  = sol.AddForceReaction()

sol.EvaluateAllResults()   # compute everything
```

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
