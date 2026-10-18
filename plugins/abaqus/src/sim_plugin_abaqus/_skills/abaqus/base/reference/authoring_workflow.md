# Abaqus CAE Authoring Workflow

Use this workflow when the agent must build and debug the model, not merely
run a completed input deck.

## Session Shape

The Abaqus plugin supports two CAE session backends. Use the default
file-backed backend when maximum isolation matters:

```powershell
uv run sim connect --solver abaqus --mode cae --ui-mode no_gui --workspace runs/abaqus_case
uv run sim exec "<Abaqus/CAE Python snippet>"
uv run sim inspect cae.model_summary
uv run sim inspect job.diagnostics
uv run sim disconnect
```

Each `uv run sim exec` call launches Abaqus/CAE for one snippet, loads the session
`.cae` database if it exists, runs the snippet, saves the database, and returns
model/workspace diagnostics. Treat this as persistent model state, not as a
live GUI process.

Use the bridge backend for faster iterative authoring:

```powershell
uv run sim connect --solver abaqus --mode cae --ui-mode no_gui --backend bridge --workspace runs/abaqus_case
uv run sim exec "<Abaqus/CAE Python snippet>"
uv run sim inspect cae.model_summary
uv run sim disconnect
```

The bridge backend keeps one noGUI CAE process alive and sends snippets through
a localhost command channel. It preserves in-memory CAE state across snippets,
returns stdout/stderr/tracebacks, saves the session `.cae` after each exec, and
still avoids GUI automation. Prefer this for agent-driven build/debug/report
loops when a local interactive process is acceptable. The bridge uses a
per-session token and should be used only in trusted workspaces owned by the
session user.

## Case Workspace

For non-trivial authoring, the `--workspace` value is the case folder, not a
throwaway temp directory. Create or verify this structure before the first real
modeling snippet:

```text
<workdir>/
  model/          # .cae database, named checkpoints, model copies
  input/          # parameters, CAD, source data, user-provided decks
  scripts/        # generated or hand-written Abaqus/CAE and ODB scripts
  run/            # solver-native job outputs: .inp, .odb, .msg, .sta, .dat
  render/         # Abaqus/CAE or Viewer PNG/MP4/viewport evidence
  output/         # metrics JSON, tables, extracted summaries
  report/         # markdown/html/pdf summary when generated
```

The driver may manage `session.cae` at the workspace root. Treat that as the
live session database, and save named checkpoints under `model/` when they help
review or resume work:

```text
model/<case_slug>_01_geometry.cae
model/<case_slug>_02_loads_mesh.cae
model/<case_slug>_03_solved.cae
```

Keep generated snippets under `scripts/` when they are meant to be reused.
Keep Abaqus job files under `run/` by setting job names and working paths
deliberately in the CAE snippets. Put Abaqus-rendered contour images,
deformed-shape views, modal views, and animations under `render/`. Put
machine-readable extrema, probes, frame inventories, and tables under
`output/`. Reports should live under `report/` and reference these artifacts by
path.

## Agent Loop

1. Capture Category A inputs: geometry, material data, units, contacts,
   loads, boundary conditions, analysis type, mesh criteria, and acceptance
   criteria.
2. Establish the case workspace, create the subfolders above, and decide the
   case slug, job name, and checkpoint names.
3. Create the model skeleton: model name, part geometry, materials, sections,
   assembly instances, datum/sets/surfaces.
4. Inspect immediately:

```powershell
uv run sim inspect cae.model_summary
```

5. Add steps, interactions, BCs, loads, output requests, and mesh controls in
   small snippets.
6. Save a named `.cae` checkpoint after each passed major layer when the model
   has become valuable to resume or review.
7. Submit a job from CAE Python only after the model summary contains the
   expected parts, materials, sections, steps, loads, BCs, instances, and job.
8. Inspect diagnostics and generated files:

```powershell
uv run sim inspect job.diagnostics
uv run sim inspect workdir.files
```

9. Render canonical review views with Abaqus/CAE or Abaqus Viewer when visual
   evidence is needed, and place them under `render/`.
10. Extract metrics or tables needed for acceptance into `output/`.
11. Fix modeling or solver issues, rerun, and only then report results under
   `report/`.

## Snippet Contract

Snippets run with Abaqus globals in scope: `mdb`, `session`,
`abaqusConstants`, and `caeModules`. To return structured data to sim, assign
JSON-serializable data to `_sim_result`:

```python
model = mdb.models["Model-1"]
_sim_result = {
    "models": list(mdb.models.keys()),
    "parts": list(model.parts.keys()),
}
```

Keep snippets idempotent where possible. Before creating an object, delete or
reuse an existing object with the same name so reruns do not leave duplicate or
stale state.

## Modeling Gates

Do not submit a job until these facts are true:

- A case workspace exists and contains the expected `model/`, `input/`,
  `scripts/`, `run/`, `render/`, `output/`, and `report/` folders or a
  deliberate documented subset.
- Units are stated in the conversation or report.
- Every part has a material and section assignment.
- The assembly contains the expected instances.
- Sets/surfaces used by BCs and loads exist.
- At least one analysis step exists after `Initial`.
- Output requests cover the acceptance quantities.
- Mesh exists and element type/order is intentional.

## When Batch Is Better

Use `uv run sim run --solver abaqus file.inp` instead when the complete model is
already available, when a deterministic generated input deck is simpler, or
when a scheduler/HPC system owns job submission.
