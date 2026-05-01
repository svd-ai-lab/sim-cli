# Abaqus CAE Authoring Workflow

Use this workflow when the agent must build and debug the model, not merely
run a completed input deck.

## Session Shape

The Abaqus plugin supports two CAE session backends. Use the default
file-backed backend when maximum isolation matters:

```powershell
sim connect --solver abaqus --mode cae --ui-mode no_gui --workspace runs/abaqus_case
sim exec "<Abaqus/CAE Python snippet>"
sim inspect cae.model_summary
sim inspect job.diagnostics
sim disconnect
```

Each `sim exec` call launches Abaqus/CAE for one snippet, loads the session
`.cae` database if it exists, runs the snippet, saves the database, and returns
model/workspace diagnostics. Treat this as persistent model state, not as a
live GUI process.

Use the bridge backend for faster iterative authoring:

```powershell
sim connect --solver abaqus --mode cae --ui-mode no_gui --backend bridge --workspace runs/abaqus_case
sim exec "<Abaqus/CAE Python snippet>"
sim inspect cae.model_summary
sim disconnect
```

The bridge backend keeps one noGUI CAE process alive and sends snippets through
a localhost command channel. It preserves in-memory CAE state across snippets,
returns stdout/stderr/tracebacks, saves the session `.cae` after each exec, and
still avoids GUI automation. Prefer this for agent-driven build/debug/report
loops when a local interactive process is acceptable. The bridge uses a
per-session token and should be used only in trusted workspaces owned by the
session user.

## Agent Loop

1. Capture Category A inputs: geometry, material data, units, contacts,
   loads, boundary conditions, analysis type, mesh criteria, and acceptance
   criteria.
2. Create the model skeleton: model name, part geometry, materials, sections,
   assembly instances, datum/sets/surfaces.
3. Inspect immediately:

```powershell
sim inspect cae.model_summary
```

4. Add steps, interactions, BCs, loads, output requests, and mesh controls in
   small snippets.
5. Submit a job from CAE Python only after the model summary contains the
   expected parts, materials, sections, steps, loads, BCs, instances, and job.
6. Inspect diagnostics:

```powershell
sim inspect job.diagnostics
sim inspect workdir.files
```

7. Fix modeling or solver issues, rerun, and only then report results.

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

- Units are stated in the conversation or report.
- Every part has a material and section assignment.
- The assembly contains the expected instances.
- Sets/surfaces used by BCs and loads exist.
- At least one analysis step exists after `Initial`.
- Output requests cover the acceptance quantities.
- Mesh exists and element type/order is intentional.

## When Batch Is Better

Use `sim run --solver abaqus file.inp` instead when the complete model is
already available, when a deterministic generated input deck is simpler, or
when a scheduler/HPC system owns job submission.
