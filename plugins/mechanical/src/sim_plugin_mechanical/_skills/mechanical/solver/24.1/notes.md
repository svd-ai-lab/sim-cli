# Ansys Mechanical 24.1 — solver layer notes

## Scripting namespace (verified 24.1)

These globals exist inside `run_python_script` on a stock 24.1 install:

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

## 24.1-specific quirks

- **`Model.Mesh.Nodes` returns an `int`** — not iterable. Same for
  `Elements`. Use `Model.Mesh.ElementIds` to iterate.
- **`Body.Material` is a string** (the material name), not a Material
  object. Assign by name.
- **`AnalysisType` printable** — `str(analysis.AnalysisType)` gives
  `"Static"` for Static Structural, `"Modal"` for Modal, etc.
- **`ResultFileName`** on an analysis returns the full path to the
  `.rst` file *after* solve. Before solve, it returns an empty string.

## File layout on 24.1

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

## Licenses consumed

- `ansys` or `mechanical_solver`: the solver engine (needed for `Solve()`).
- `struct_solver`: advanced features (nonlinear contact, etc.).

A minimal structural solve needs one `ansys` feature.
