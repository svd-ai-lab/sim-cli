# Workbench Analysis System Templates

Available system templates for `GetTemplate(TemplateName=...)`.
Verified on Ansys 24.1.

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
- `Solver` parameter values: `"ANSYS"` (Mechanical), `"FLUENT"`,
  `"CFX"`, `"MAXWELL"`, etc.
- Some templates may not be available if the corresponding product is
  not installed.
