# Fluent-specific runtime dependencies

The generic connect / exec / inspect / disconnect loop, step-execution
pattern, state-query pattern, failure handling, and acceptance
evaluation all live in the shared sim-cli skill:

- [`sim-cli/reference/lifecycle.md`](../../../sim-cli/reference/lifecycle.md) — patterns 0–6
- [`sim-cli/reference/command_surface.md`](../../../sim-cli/reference/command_surface.md)
- [`sim-cli/reference/escalation.md`](../../../sim-cli/reference/escalation.md)
- [`sim-cli/reference/acceptance.md`](../../../sim-cli/reference/acceptance.md)

This file covers only the **Fluent-specific** dependency rules that the
generic patterns do not capture.

---

## Pattern 7 — Multi-step dependency ordering

**Rule**: never send step N+1 before step N is confirmed successful.
This is a Fluent rule because the meshing and solver task lists are
stateful — an out-of-order call mutates session state in ways that are
hard to undo.

### Meshing (watertight)

```
InitializeWorkflow → ImportGeometry → LocalSizing → SurfaceMesh
→ DescribeGeometry → UpdateBoundaries → UpdateRegions
→ BoundaryLayers → VolumeMesh → SwitchToSolver
```

### Meshing (fault-tolerant)

```
InitializeWorkflow → ImportCAD → CreateRegions → LocalSizing
→ GenerateSurfaceMesh → UpdateBoundaries → CreateVolumeMesh
→ SwitchToSolver
```

### Solver

```
ReadCase → ReadData → MeshCheck → Iterate → ExtractResults
```

If a step is skippable (e.g. `LocalSizing` defaults are acceptable),
explicitly note in the report that it was skipped and why. Do not
silently drop steps.

---

## Pattern 8 — Mode-specific flag rules

`--mode meshing` and `--mode solver` are not interchangeable. Which
snippets are valid depends on the mode:

| Mode | Valid snippet families |
|---|---|
| `meshing` | Watertight / fault-tolerant meshing snippets (`base/snippets/01_*` through pre-switch) |
| `solver` | Post-`SwitchToSolver` snippets (`05a_setup_bcs_*` onward) |

Running a solver snippet in meshing mode (or vice versa) fails with
`AttributeError` on a missing module — there is no informative runtime
check, so the agent must respect the mode.

---

## Pattern 9 — Settings vs TUI selection

See `tui_vs_settings.md`. Short version: prefer the Settings API for
new workflows; fall back to TUI commands only for features the Settings
API has not yet surfaced (named expression tagging in 0.37, some
solution-controls knobs). The Settings API is the durable interface.
