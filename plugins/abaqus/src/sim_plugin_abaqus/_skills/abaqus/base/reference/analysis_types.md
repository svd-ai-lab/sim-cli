# Abaqus Analysis Types

> Applies to: Abaqus 2024-2026
> Last verified: 2026-04-13

## Overview

Abaqus supports a wide range of analysis types via the `*STEP` keyword
in input decks or `model.XXXStep()` in Python scripts.

## Structural Analysis

| Type | Keyword | Python | Use case |
|------|---------|--------|----------|
| Static | `*STATIC` | `StaticStep()` | Linear/nonlinear static loading |
| Dynamic Implicit | `*DYNAMIC` | `ImplicitDynamicsStep()` | Moderate-speed dynamic events |
| Dynamic Explicit | `*DYNAMIC, EXPLICIT` | (Abaqus/Explicit) | High-speed impact, crash |
| Static Riks | `*STATIC, RIKS` | `StaticRiksStep()` | Buckling, snap-through |
| Frequency | `*FREQUENCY` | `FrequencyStep()` | Natural frequencies, mode shapes |
| Steady-state dynamics | `*STEADY STATE DYNAMICS` | `SteadyStateDirectStep()` | Harmonic response |
| Modal dynamics | `*MODAL DYNAMIC` | `ModalDynamicsStep()` | Transient via mode superposition |

## Thermal Analysis

| Type | Keyword | Use case |
|------|---------|----------|
| Heat transfer | `*HEAT TRANSFER` | Steady-state or transient conduction |
| Coupled temp-displacement | `*COUPLED TEMPERATURE-DISPLACEMENT` | Thermomechanical |

## Other Analysis Types

| Type | Keyword | Use case |
|------|---------|----------|
| Geostatic | `*GEOSTATIC` | Initial stress state for soil/rock |
| Soils | `*SOILS` | Consolidation analysis |
| Coupled pore fluid | `*SOILS, CONSOLIDATION` | Pore pressure diffusion |
| Mass diffusion | `*MASS DIFFUSION` | Concentration-driven diffusion |
| Electromagnetic | `*ELECTROMAGNETIC` | Eddy current, magnetostatic |

## Choosing the Right Analysis

```
Static loading?
  ├── Linear material + small deformation → *STATIC (fastest)
  ├── Nonlinear material or large deformation → *STATIC, NLGEOM
  └── Buckling/instability → *STATIC, RIKS

Dynamic loading?
  ├── Slow/moderate (< 10 m/s impact) → *DYNAMIC (implicit)
  ├── Fast/severe (crash, blast) → *DYNAMIC, EXPLICIT
  └── Vibration/harmonic → *FREQUENCY + *STEADY STATE DYNAMICS

Thermal?
  ├── Temperature only → *HEAT TRANSFER
  └── Temperature + deformation → *COUPLED TEMPERATURE-DISPLACEMENT
```

## Common Step Parameters

```
*STEP, NAME=LoadStep, NLGEOM=YES    # nonlinear geometry
*STATIC
0.1, 1.0, 1e-5, 0.1                # initial_inc, total_time, min_inc, max_inc
```

- `NLGEOM=YES` — enable geometric nonlinearity (large deformation)
- Time increments control convergence (smaller = more robust, slower)
- Multiple steps can be chained in sequence
