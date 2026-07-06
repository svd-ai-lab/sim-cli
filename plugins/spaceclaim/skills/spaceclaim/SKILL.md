---
name: spaceclaim
description: Work with Ansys SpaceClaim or Discovery CAD geometry through local executables, SpaceClaim scripting/API, GUI-assisted workflows, or solver-prep handoff. Use when Codex needs to inspect, repair, defeature, import/export, script, extract enclosures or fluid domains, create named geometry, or prepare CAD for Fluent, Mechanical, COMSOL, or another solver.
---

# SpaceClaim Skill

Use this skill for Ansys SpaceClaim CAD preparation and geometry automation.
SpaceClaim is usually a desktop geometry/preprocessing tool, not the solver
itself. Prefer the narrowest path that gives real evidence: file inspection for
simple inventory, SpaceClaim scripts for repeatable geometry commands, GUI
operation for semantic face/body choices, and solver-specific tools after the
geometry is exported.

## Working Approach

1. Probe availability before launching SpaceClaim when local state is unknown.
   - Run `scripts/probe_spaceclaim.ps1` when working on Windows.
   - Acceptable alternatives: `Get-Command SpaceClaim.exe`, common Ansys
     install-path checks, Registry checks, or a user-provided
     `SIM_SPACECLAIM_ROOT`.
   - Missing `sim-cli`, Python, or PyFluent is not evidence that SpaceClaim is
     missing; SpaceClaim often runs its own scripting host inside the desktop
     app.
2. Inspect inputs before changing them.
   - List CAD files and sidecars.
   - For STEP, read the header/schema/unit lines and a small topology sample
     before opening the full model.
   - Prefer writing derived files beside the original CAD instead of in-place
     edits.
3. Choose the control path by task.
   - **Batch/script**: imports, exports, simple body operations, repeatable
     named groups, repair sequences, or documented commands.
   - **GUI-assisted**: face selections, cap selections, seed points, periodic
     cuts, flow-path choices, or anything requiring design intent.
   - **Solver handoff**: meshing, boundary physics, convergence, and result
     validation belong in Fluent/Mechanical/COMSOL/etc. after CAD prep.
4. After each meaningful change, verify the artifact rather than only the
   process exit.
   Check output file existence, format, units, body/face counts when available,
   and screenshots or exported geometry for visually sensitive work.
5. Report uncertainty plainly. When the API cannot expose the geometry
   semantics needed for safe automation, produce a semi-automatic workflow or
   script template and identify the exact user selection still needed.

## Common Workflows

### Capability Probe

From PowerShell:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/probe_spaceclaim.ps1
```

Use the JSON-like output to identify:

- SpaceClaim executable path and Ansys version root.
- Nearby scripting/API XML or CHM documentation.
- Whether command names relevant to the task appear in local docs.

For a targeted check:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/probe_spaceclaim.ps1 `
  -CommandNames VolumeExtract,Enclosure,NamedSelection,Export
```

### Fluid Domain or Enclosure Extraction

Start with geometry evidence:

- Which file is the single part/module versus assembly.
- STEP units and whether closed shells/solids are present.
- Which openings are inlets, outlets, vents, periodic cuts, or artificial
  manufacturing splits.

Use SpaceClaim `VolumeExtract` or `Enclosure` after the flow region is defined.
Fully unattended extraction is most reliable for simple, unambiguous models. If
inlet/outlet caps or seed points are ambiguous, switch to GUI-assisted
operation and leave a script/workflow for the repeatable parts.

Export a solver-ready neutral file such as STEP, Parasolid, or a solver-native
project, then hand off to the solver skill/tool for meshing and physics.

### Scripted Geometry Edits

Prefer a small script that:

1. Opens/imports the source file.
2. Runs one class of operation.
3. Creates named outputs or groups.
4. Exports to a new file.
5. Prints a short summary.

Before relying on a command signature, inspect the local versioned API docs or
record a small operation in SpaceClaim's script recorder. SpaceClaim command
surfaces differ by version and installation channel.

### GUI-Assisted Work

Use the GUI when a person needs to decide design intent. Common GUI-driven
selections include:

- Selecting which faces are fuel inlet, oxidizer inlet, outlet, wall, symmetry,
  or periodic boundaries.
- Choosing the internal cavity versus exterior air.
- Defeaturing geometry where removing the wrong feature changes the physics.

The useful agent role is to prepare the file, propose the selections, drive or
observe SpaceClaim where possible, and verify the exported geometry.

## Evidence

- A found executable proves installation, not licensing or script success.
- A successful launch proves transport, not a valid CAD operation.
- A generated script proves preparation, not completed geometry extraction.
- A solver-ready export plus inspection evidence is the minimum proof that CAD
  prep completed.

For an agent-oriented assessment of SpaceClaim's API, read
`references/api-agent-assessment.md`.
