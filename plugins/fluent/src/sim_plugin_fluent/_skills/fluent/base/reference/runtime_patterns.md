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

### Partially premixed flamelet/PDF

```
ReadMeshOrCase → SetDimension/Axisymmetric → Energy/Turbulence
→ PartiallyPremixedModel → CHEMKINImportAsFlameletMixture
→ SetFuelOxidizerStreams → CalcFlamelets → CalcPDFTable
→ WritePDFTable → InspectBoundaryScalars → SetCFDBoundaries
→ InitializeOrRestart → Iterate → WriteCaseData
→ FreshSessionReadCase → ReadPDFTable → ReadData → ExtractResults
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

---

## Pattern 10 — Reacting PDF/flamelet runs need staged physical state

Lookup-table and transported-PDF combustion models are not just model
toggles. They often require imported/generated chemistry data, boundary
composition setup, and a physically developed initial solution before
the production solve.

For partially premixed steady-diffusion flamelet/PDF table workflows:

1. Set `species.model.option = "partially-premixed-combustion"` first.
2. Set the chemistry state relation and energy treatment before importing
   CHEMKIN.
3. Import CHEMKIN with the material name `"flamelet-mixture"`, followed by
   the mechanism and thermo file paths.
4. Set fuel/oxidizer stream composition in
   `partially_premixed_model_options.boundary`.
5. Generate flamelets with `root.flamelet.parameters.calc_fla()`.
6. Generate the PDF table with `root.table.calc_pdf()`.
7. Persist the table separately with `root.table.write_pdf_cmd(...)`.
8. On restart or postprocessing, read in the order
   `read_case -> read_pdf -> read_data`.

For Composition PDF Transport in particular:

1. Import the CHEMKIN mechanism and thermodynamic data first.
2. Enable the PDF transport model and verify the selected mixture
   material and number of volumetric species.
3. Set only the explicitly listed inlet species mass fractions; the
   final species may be a balance species that cannot be created as a
   boundary entry.
4. Prefer restarting from a developed finite-rate, EDC, non-premixed, or
   partially-premixed solution instead of cold-starting from a mesh.
5. Treat particle tracking and residual decrease as necessary but not
   sufficient. Monitor temperature/species profiles, outlet composition,
   and heat balance until the composition statistics stop moving.

If a short cold-start run produces ambient downstream profiles, do not
spend more iterations blindly. Confirm that the model has a valid
reacting initial field and that boundary compositions survived the model
switch.
