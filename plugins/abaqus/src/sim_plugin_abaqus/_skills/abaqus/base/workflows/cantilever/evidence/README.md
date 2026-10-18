# Abaqus E2E Evidence - Cantilever Beam

**Date**: 2026-04-13
**Solver**: Abaqus 2026

## Model

| Parameter | Value |
|---|---|
| Type | Cantilever beam under tip load |
| Geometry | L=10 m, b=1 m, h=1 m |
| Material | Steel, E=200 GPa, nu=0.3 |
| Load | P=-1000 N at the tip node |
| Boundary condition | Fixed support at the left edge |
| Elements | 4 CPS4 plane-stress elements |
| Nodes | 10 |

## Analytical Reference

Euler-Bernoulli beam theory gives:

```text
delta = P L^3 / (3 E I) = 2e-5 m
```

## FEM Result

| Output | Value |
|---|---|
| Tip U1 | -4.29e-7 m |
| Tip U2 | -5.75e-6 m |
| Tip deflection magnitude | 5.75e-6 m |

## Validation

- Tip deflection is inside the expected smoke-test range of 1e-7 m to 1e-4 m.
- The coarse 4-element CPS4 mesh is stiffer than beam theory, which is expected
  for this intentionally small smoke model.
- Abaqus reported job completion.
- The structured result reported `ok=true` and no parsed solver errors.

## Run Record

```text
--- Test 1: .inp direct ---
[sim] run:    abaqus_e2e_cantilever.inp via abaqus
[sim] status: converged

--- Test 2: Python wrapper ---
{"ok": true, "node": 5, "U1_m": -4.2898087e-07, "U2_m": -5.7521961e-06,
 "tip_deflection_m": 5.7521961e-06, "solver_output": "Abaqus completed successfully"}
```

## Files

- `e2e_summary.json` - structured result data.
- `cantilever_deformation.png` - Abaqus/CAE noGUI contour export.
- `run/` - minimal evidence subset retained for this skill workflow.
