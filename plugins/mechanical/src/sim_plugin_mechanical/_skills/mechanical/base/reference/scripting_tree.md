# Mechanical scripting tree

Every snippet you send via `run_python_script` runs inside Mechanical's
embedded IronPython 2.7 interpreter. These names are **already globals**
— do not import them:

| Global | What it is |
|---|---|
| `ExtAPI` | Top-level automation object. Everything hangs off this. |
| `DataModel` | Shortcut for `ExtAPI.DataModel`. |
| `Model` | Shortcut for `ExtAPI.DataModel.Project.Model`. |
| `Tree` | The Mechanical outline tree widget — use `Tree.Refresh()` after structural changes. |
| `Quantity` | Constructor for physical quantities: `Quantity("10 [MPa]")`. |
| `MechanicalEnums` | All enums (`LoadDefineBy`, `AnalysisType`, ...). |
| `Transaction` | `with Transaction(): ...` batches UI updates. |

## Core traversal patterns

```python
project = ExtAPI.DataModel.Project
model   = project.Model
analyses = model.Analyses                  # list-like
first    = analyses[0]
solution = first.Solution
results  = solution.Children               # Total Deformation, Equivalent Stress, ...
```

### Bodies and geometry

```python
geom = Model.Geometry
bodies = list(geom.GetChildren(DataModelObjectCategory.Body, True))
# Each Body has: .Name, .Material, .Thickness (2D), .Dimensions, .GetGeoBody()
```

### Mesh

```python
mesh = Model.Mesh
print(mesh.Nodes, mesh.Elements)   # these are ints, not collections
mesh.GenerateMesh()
```

### Named selections (use these for BC scoping!)

```python
ns = Model.NamedSelections
# After a geometry import, named selections from the CAD travel with it.
fixed_face = [ns_i for ns_i in ns.Children if ns_i.Name == "fixed"][0]
```

### Creating a new load or BC

```python
# Get the analysis
static = Model.Analyses[0]   # e.g. Static Structural

# Add a fixed support
fs = static.AddFixedSupport()
fs.Location = fixed_face     # NamedSelection works directly

# Add a pressure
press = static.AddPressure()
press.Location = loaded_face
press.Magnitude.Output.DiscreteValues = [Quantity("1 [MPa]"), Quantity("1 [MPa]")]
```

## Solve

```python
static = Model.Analyses[0]
static.Solve(True)    # True = wait for solve to finish
# Check state
print(static.Solution.Status)   # Done, Failed, ...
```

## Result query

```python
sol = Model.Analyses[0].Solution
td  = sol.AddTotalDeformation()
sol.EvaluateAllResults()
max_def = td.Maximum           # Quantity object
print(str(max_def))            # e.g. "0.00123 m"
```

## Common gotchas

1. **`Model.Mesh.Nodes` is an int, not a collection.** Same for
   `Elements`. To iterate, use `Mesh.ElementIds`.
2. **`body.Material` is a string (the material name), not a Material
   object.** Assign by name: `body.Material = "Structural Steel"`.
3. **`Location` on a BC accepts `NamedSelection`, `SelectionInfo`, or
   a list of GeoEntity IDs.** It does NOT accept raw `Body` objects.
4. **Enum values are under `MechanicalEnums.<Category>`** — e.g.
   `MechanicalEnums.BoundaryCondition.Pressure`.
5. **Tree edits during iteration break the enumerator.** Collect first,
   mutate second.
6. **IronPython 2.7**: no f-strings, no `print()` as a function in all
   cases — use `print(x)` which works in IronPython's CPython-compat mode
   but never `print(f"{x}")`.

## Structured output pattern

```python
import json

result = {}
try:
    static = Model.Analyses[0]
    result["status"] = str(static.Solution.Status)
    result["max_deformation_m"] = static.Solution.Children[0].Maximum.Value
    result["ok"] = True
except Exception as e:
    result["ok"] = False
    result["error"] = str(e)

json.dumps(result)   # <-- last expression
```

sim's MechanicalDriver parses the last JSON line from stdout into the
`result` field of the exec response.
