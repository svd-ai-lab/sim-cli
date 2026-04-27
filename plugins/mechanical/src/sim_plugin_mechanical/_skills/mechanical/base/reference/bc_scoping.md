# Boundary condition scoping

BC scoping is **the #1 source of Mechanical scripting errors**. This
doc is a short survival guide.

## The three flavors of Location

A BC's `.Location` accepts one of:

1. **`NamedSelection`** — the easy path. Create named selections
   beforehand (via SpaceClaim, DesignModeler, or CAD tags) so they travel
   with the geometry.
2. **`SelectionInfo`** — built by the selection manager from entity IDs.
3. **List of geometry IDs** via `ExtAPI.SelectionManager`.

### NamedSelection (preferred)

```python
ns = [x for x in Model.NamedSelections.Children if x.Name == "fixed_end"][0]

fs = Model.Analyses[0].AddFixedSupport()
fs.Location = ns
```

### SelectionInfo (when you must)

```python
sm = ExtAPI.SelectionManager
sm.ClearSelection()

# Option A: select all faces of body 0
body = Model.Geometry.GetChildren(DataModelObjectCategory.Body, True)[0]
face_ids = [f.GetGeoEntity().Id for f in body.GetGeoBody().Faces]

sel = ExtAPI.SelectionManager.CreateSelectionInfo(SelectionTypeEnum.GeometryEntities)
sel.Ids = face_ids

fs = Model.Analyses[0].AddFixedSupport()
fs.Location = sel
```

### Common mistakes

| Mistake | What happens | Fix |
|---|---|---|
| `fs.Location = body` | `TypeError: Location` does not accept Body | Use `body.GetGeoBody().Faces` to get faces, then `SelectionInfo` |
| `fs.Location = body.GetGeoBody().Faces[0]` | silently does nothing | Must wrap in `SelectionInfo` |
| `fs.Location = [face_id]` | `TypeError: expected SelectionInfo` | Wrap: `sel.Ids = [face_id]; fs.Location = sel` |
| Selecting before `Tree.Refresh()` | IDs stale after geometry re-import | `Tree.Refresh()` first |

## Loads: the magnitude APIs

Loads typically have two ways to set magnitude:

```python
# 1. Direct: for constant loads
pressure = Model.Analyses[0].AddPressure()
pressure.Magnitude.Output.DiscreteValues = [Quantity("1 [MPa]"), Quantity("1 [MPa]")]

# 2. Expression: for time/space-varying loads
pressure.Magnitude.Inputs[0].DiscreteValues = [Quantity("0 [s]"), Quantity("1 [s]")]
pressure.Magnitude.Output.DiscreteValues = [Quantity("0 [MPa]"), Quantity("10 [MPa]")]
```

Use `DefineBy` to switch modes:

```python
from MechanicalEnums import LoadDefineBy
pressure.DefineBy = LoadDefineBy.Components
```

## Common BCs cheat sheet

| BC | Method | Required fields |
|---|---|---|
| Fixed Support | `analysis.AddFixedSupport()` | `Location` |
| Displacement | `analysis.AddDisplacement()` | `Location`, `XComponent`/`YComponent`/`ZComponent` |
| Pressure | `analysis.AddPressure()` | `Location`, `Magnitude` |
| Force | `analysis.AddForce()` | `Location`, `Magnitude` / `XComponent`... |
| Moment | `analysis.AddMoment()` | `Location`, `Magnitude` |
| Remote Force | `analysis.AddRemoteForce()` | `Location`, `XComponent`... |
| Standard Earth Gravity | `analysis.AddStandardEarthGravity()` | `Direction` |
| Thermal Condition | `analysis.AddThermalCondition()` | `Location`, `Magnitude` |

## Verifying a BC landed

After creating a BC, always verify:

```python
bc = Model.Analyses[0].Children[-1]  # last-added
print(bc.Name, bc.Suppressed, bc.ScopingMethod)
print("Location set:", bc.Location is not None)
```

If `Location` is None, the scoping failed silently — Mechanical won't
error until solve time.
