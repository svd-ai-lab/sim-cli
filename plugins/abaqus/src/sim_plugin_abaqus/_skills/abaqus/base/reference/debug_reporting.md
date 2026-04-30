# Abaqus Debugging and Reporting

Agent work is not complete when Abaqus exits. Treat solver completion as one
signal, then verify the model and results against engineering criteria.

## Debug Sources

Inspect these outputs after every job:

| File | Purpose | What to look for |
|---|---|---|
| `.msg` | Solver messages | errors, warnings, convergence problems, contact issues |
| `.sta` | Step/increment status | completed increments, cutbacks, aborts |
| `.dat` | Text results and summaries | requested nodal/element output, warnings |
| `.odb` | Binary result database | field outputs for reporting plots and extrema |
| `.com` | Command echo | job options and command context |

Use:

```powershell
sim inspect job.diagnostics
sim inspect workdir.files
```

## Debug Loop

1. Classify the failure: modeling error, missing set/surface, material/section
   issue, mesh quality, contact, convergence, license/environment, or
   post-processing.
2. Fix the smallest model element that explains the failure.
3. Re-inspect the model summary before rerunning.
4. Rerun and compare diagnostics against the previous attempt.
5. Record what changed and why in the final report.

## Report Checklist

A usable Abaqus report should include:

- Objective and acceptance criteria.
- Unit system and coordinate conventions.
- Geometry/parts, materials, sections, and element types.
- Boundary conditions, loads, contacts/interactions, and analysis steps.
- Mesh summary and any mesh-quality caveats.
- Solver status: completed/failed, key warnings/errors, increments/cutbacks.
- Result quantities tied to acceptance criteria.
- Engineering interpretation: pass/fail, margin, and dominant assumptions.
- Reproducibility: input deck or CAE script path, job name, and output files.

## Report Tone

Be explicit about uncertainty. If a result is only a coarse smoke, call it a
coarse smoke. If convergence warnings remain, do not present the result as a
validated design result.
