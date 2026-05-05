# Ansys Mechanical solver layer notes

## Scripting namespace

These globals are expected inside `run_python_script` for supported
Mechanical sessions:

| Global | Kind | Notes |
|---|---|---|
| `ExtAPI` | object | Entry point. `ExtAPI.DataModel.Project`. |
| `DataModel` | alias | Same as `ExtAPI.DataModel`. |
| `Model` | alias | Same as `ExtAPI.DataModel.Project.Model`. |
| `Tree` | object | Outline widget. `Tree.Refresh()` after structural changes. |
| `Quantity` | ctor | `Quantity("10 [MPa]")`. |
| `MechanicalEnums` | module | All enums. 24.1 adds `MechanicalEnums.Common.MessageSeverityType`. |
| `DataModelObjectCategory` | enum | Used with `GetChildren(category, recursive)`. |
| `SelectionTypeEnum` | enum | For `CreateSelectionInfo`. |

## Solver quirks

- **`Model.Mesh.Nodes` returns an `int`** — not iterable. Same for
  `Elements`. Use `Model.Mesh.ElementIds` to iterate.
- **`Body.Material` is a string** (the material name), not a Material
  object. Assign by name.
- **`AnalysisType` printable** — `str(analysis.AnalysisType)` gives
  `"Static"` for Static Structural, `"Modal"` for Modal, etc.
- **`ResultFileName`** on an analysis returns the full path to the
  `.rst` file *after* solve. Before solve, it returns an empty string.

## File layout

```
%TEMP%/AnsysMech<pid>/
├── <project>.mechdb
├── file.rst
├── file.err
├── solver.out
└── ...
```

Use `client.list_files()` to discover the actual working directory
(it changes every launch).

## Solver availability

If `Solve()` hangs or returns without producing result state, inspect
`session.health`, `mechanical.project.identity`, `mechanical.model.summary`,
and solver output artifacts before retrying a larger script.
