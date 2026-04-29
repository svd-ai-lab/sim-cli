# Workbench Analysis System Templates

Available system templates for `GetTemplate(TemplateName=...)`.
Verified on Ansys 24.1.

Before assuming a template exists, ask the live Workbench session:

```python
templates = GetAllVisibleTemplates()
```

On a 2025 R2 install without the Mechanical product layer, the visible
template list included CFD and optimization entries such as `FLUENT`,
`Fluid Flow`, `Geometry`, and `Results`, but did **not** include
`Static Structural`. In that environment,
`GetTemplate(TemplateName="Static Structural", Solver="ANSYS")` raises
`Template Static Structural (ANSYS) not found in Project.` Treat this as
a missing product/template condition, not a PyWorkbench launch failure.

## Structural

| Template Name | Solver | Components |
|--------------|--------|------------|
| `"Static Structural"` | ANSYS | Engineering Data, Geometry, Model, Setup, Solution, Results |
| `"Transient Structural"` | ANSYS | Same as Static Structural |
| `"Modal"` | ANSYS | Same as Static Structural |
| `"Harmonic Response"` | ANSYS | Same as Static Structural |
| `"Random Vibration"` | ANSYS | Same as Static Structural |
| `"Response Spectrum"` | ANSYS | Same as Static Structural |
| `"Explicit Dynamics"` | ANSYS | Same as Static Structural |

## Thermal

| Template Name | Solver | Components |
|--------------|--------|------------|
| `"Steady-State Thermal"` | ANSYS | Engineering Data, Geometry, Model, Setup, Solution, Results |
| `"Transient Thermal"` | ANSYS | Same as Steady-State Thermal |

## CFD

| Template Name | Solver | Accessible Components |
|--------------|--------|----------------------|
| `"FLUENT"` | (auto) | Setup, Solution (Geometry/Mesh/Results managed by Fluent solver) |
| `"Fluid Flow (CFX)"` | (auto) | Setup, Solution |
| `"Fluid Flow"` | (auto) | Setup, Solution |

> **Note**: On Ansys 24.1, use `"FLUENT"` (uppercase, no Solver param), not
> `"Fluent"` with `Solver="FLUENT"` as shown in official docs. CFD systems
> only expose Setup and Solution via `GetContainer()` — mesh and results are
> accessed through the solver's own API (PyFluent, CFX-Pre, etc.).

## Electromagnetics

| Template Name | Solver | Components |
|--------------|--------|------------|
| `"Maxwell 2D"` | MAXWELL | Geometry, Setup, Solution, Results |
| `"Maxwell 3D"` | MAXWELL | Geometry, Setup, Solution, Results |

## Usage

```python
SetScriptVersion(Version="24.1")

# Create a Static Structural system
template1 = GetTemplate(TemplateName="Static Structural", Solver="ANSYS")
system1 = template1.CreateSystem()

# Create a Fluent system
template2 = GetTemplate(TemplateName="Fluent", Solver="FLUENT")
system2 = template2.CreateSystem()
```

## Notes

- The exact list of available templates depends on the installed Ansys
  products and licenses.
- Use `GetAllVisibleTemplates()` during smoke setup and skip or choose a
  template that is present instead of assuming Mechanical templates exist.
- `Solver` parameter values: `"ANSYS"` (Mechanical), `"FLUENT"`,
  `"CFX"`, `"MAXWELL"`, etc.
- Some templates may not be available if the corresponding product is
  not installed.
