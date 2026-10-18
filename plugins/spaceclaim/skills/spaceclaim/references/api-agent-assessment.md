# SpaceClaim API Agent Assessment

## Bottom Line

SpaceClaim is useful for agents as a CAD-prep co-pilot, especially on Windows
machines that already have Ansys installed. It is less agent-friendly than
solver APIs such as PyAEDT/PyFluent because many operations are selection- and
design-intent-driven. Treat it as a strong semi-automatic geometry tool, not a
fully reliable headless CAD service.

## Strengths

- Local Ansys installs usually include SpaceClaim executables and versioned API
  assemblies/docs near the install root.
- The scripting surface exposes command-style operations such as import/export,
  repair/prepare operations, `VolumeExtract`, and `Enclosure` when licensed and
  available in that version.
- Script recorder output can turn a manual operation into a reusable template.
- It is well positioned between raw CAD files and solvers: extract fluid
  regions, create enclosures, defeature, split bodies, and prepare named
  boundaries before Fluent/Mechanical/COMSOL work.

## Weaknesses

- Many commands depend on active selections, face/body IDs, or a seed point.
  Those are brittle across regenerated CAD and are often not meaningful from
  STEP text alone.
- The API is versioned and desktop-oriented. Command signatures and launch flags
  should be checked against local docs or recorder output instead of assumed.
- SpaceClaim scripting commonly runs inside the SpaceClaim desktop host, not a
  normal CPython process. Ordinary Python package availability is therefore not
  a reliable control signal.
- Headless execution, licensing, and modal dialogs can make unattended
  automation fragile.
- The API can create or export geometry, but it does not validate solver
  physics. Mesh quality, boundary conditions, and solution correctness belong
  to the downstream solver workflow.

## Good Agent Fit

- Inventory local Ansys/SpaceClaim capability.
- Inspect CAD file types, units, and basic topology before opening the GUI.
- Generate SpaceClaim scripts for repeatable operations.
- Use GUI-assisted steps for ambiguous selections, then continue automation.
- Export clean geometry and verify output before solver handoff.

## Poor Agent Fit

- Blindly extracting a fluid domain from an arbitrary assembly.
- Guessing inlet/outlet/wall/periodic semantics from unlabelled CAD.
- Claiming a model is solver-ready without an exported geometry artifact and
  inspection evidence.
- Treating a found `SpaceClaim.exe` path as proof that scripting, licensing, and
  the requested command all work.

## Practical Grade

For current agent work, SpaceClaim API support is a **B-/B**:

- **B+** for local discovery, script-template generation, import/export, and
  semi-automatic preprocessing.
- **B-** for fully unattended geometry extraction and repair, because geometry
  semantics often require human or visual confirmation.
- **C** for true headless automation compared with APIs designed for remote
  programmatic control.

The best product shape is a hybrid: let the agent prepare and verify everything
that is machine-readable, then ask for or drive the few semantic GUI selections
that cannot be inferred safely.
