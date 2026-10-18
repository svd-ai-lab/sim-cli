# Abaqus Input Deck Reference (.inp)

> Applies to: Abaqus 2024-2026
> Last verified: 2026-04-13

## Overview

Abaqus input decks are keyword-driven text files. Each keyword starts
with `*` in column 1. Data lines follow keywords. Comments start with
`**`.

## File Structure

```
*HEADING
  Title text
**
** Nodes and elements
*NODE
  nodeID, x, y, z
*ELEMENT, TYPE=<type>, ELSET=<name>
  elemID, node1, node2, ...
**
** Materials and sections
*MATERIAL, NAME=<name>
*ELASTIC
  E, nu
*SOLID SECTION, ELSET=<name>, MATERIAL=<name>
  thickness,
**
** Sets
*NSET, NSET=<name>
  node1, node2, ...
*ELSET, ELSET=<name>
  elem1, elem2, ...
**
** Analysis step
*STEP
*STATIC | *DYNAMIC | *HEAT TRANSFER | ...
*BOUNDARY
  nodeOrSet, dof1, dof2, value
*CLOAD
  nodeOrSet, dof, magnitude
*NODE PRINT, NSET=<name>
  U, | RF, | S,
*END STEP
```

## Key Keywords

| Keyword | Purpose | Required data |
|---------|---------|---------------|
| `*HEADING` | Job title | Free text on next line |
| `*NODE` | Define nodes | ID, x, y, z |
| `*ELEMENT` | Define elements | ID, connectivity |
| `*MATERIAL` | Start material definition | NAME parameter |
| `*ELASTIC` | Isotropic elasticity | E, nu |
| `*DENSITY` | Material density | rho |
| `*SOLID SECTION` | Assign material to elements | ELSET, MATERIAL |
| `*SHELL SECTION` | Shell elements | ELSET, MATERIAL, thickness |
| `*BEAM SECTION` | Beam elements | SECTION, ELSET, MATERIAL |
| `*STEP` | Begin analysis step | — |
| `*STATIC` | Static analysis | (optional time increments) |
| `*DYNAMIC` | Dynamic analysis | time period, increment |
| `*BOUNDARY` | Displacement BC | node/set, dof range, value |
| `*CLOAD` | Concentrated load | node/set, dof, magnitude |
| `*DLOAD` | Distributed load | elem/set, face, magnitude |
| `*NODE PRINT` | Text output | field keys (U, RF, S) |
| `*NODE FILE` | Binary output (.fil) | field keys |
| `*OUTPUT` | ODB output control | — |
| `*END STEP` | End analysis step | — |

## Common Element Types

| Type | Description | Nodes |
|------|-------------|-------|
| `CPS3` | 2D plane stress triangle | 3 |
| `CPS4` | 2D plane stress quad | 4 |
| `CPS4R` | 2D plane stress quad, reduced integration | 4 |
| `CPE4` | 2D plane strain quad | 4 |
| `C3D8` | 3D hex (brick) | 8 |
| `C3D8R` | 3D hex, reduced integration | 8 |
| `C3D10` | 3D tet | 10 |
| `C3D20` | 3D hex, quadratic | 20 |
| `S4R` | Shell quad, reduced integration | 4 |
| `B31` | 2-node beam | 2 |
| `T2D2` | 2-node truss | 2 |

## Output Parsing

Abaqus writes results to:
- `.dat` — text-format field output (from `*NODE PRINT`, `*EL PRINT`)
- `.odb` — binary database (for post-processing in CAE)
- `.sta` — status file (convergence info per increment)
- `.msg` — solver messages (warnings, errors)

For `sim` integration, parse `.dat` for numeric results. The displacement
table format:

```
NODE FOOT-  U1             U2             U3
     NOTE
   5     -4.2898E-07 -5.7522E-06  0.0000E+00
```

## Gotchas

- Keywords are case-insensitive but conventionally uppercase
- Data lines must follow their keyword immediately (no blank lines)
- Set names max 80 characters
- `*SOLID SECTION` thickness line needs trailing comma for 2D
- Abaqus uses Fortran-style scientific notation in output (E+00)
