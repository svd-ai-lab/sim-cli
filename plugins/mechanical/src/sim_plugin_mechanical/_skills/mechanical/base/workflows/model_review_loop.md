# Mechanical model review loop

Use this loop for every non-trivial Mechanical setup, solve, or result
extraction task. Mechanical state is layered: a solve failure often comes from
geometry, scoping, mesh, or boundary-condition state created earlier.

## Loop

1. Inspect `uv run sim inspect session.health`.
2. Inspect `uv run sim inspect mechanical.project.identity`.
3. Inspect `uv run sim inspect mechanical.model.summary`.
4. For any non-routine analysis/load/result type, inspect
   `uv run sim inspect mechanical.capabilities` or
   `uv run sim inspect mechanical.capabilities:analysis:<index>` before writing setup
   code.
5. Before a long-running solve/update/import, capture a screenshot and decide
   what out-of-band signal will be checked while the SDK call is blocked:
   screenshots, `mechanical.messages`, solver files, or visible progress.
6. Execute one bounded IronPython snippet.
7. Inspect `uv run sim inspect last.result`.
8. Re-inspect `mechanical.model.summary`; after solve/result failures also
   inspect `uv run sim inspect mechanical.messages`.
9. In GUI mode, capture or review a screenshot after significant visible tree
   changes.
10. Continue only when structured state and visual state match the intended
   setup.

## Checkpoints

| Layer | Expected evidence |
|---|---|
| Project | Health is ok; project identity names an active model state; checkpoint readiness is understood. |
| Analysis | Expected analysis type exists before adding setup objects. |
| Capabilities | Live method lists contain the analysis, load/BC, and result APIs needed for the workflow. |
| Geometry | Body count is nonzero before applying supports, loads, mesh controls, or results. |
| Selections | Named selections or selection info objects are non-empty and match the intended entity dimension. |
| Mesh | Mesh node/element counts are plausible for the geometry. |
| Setup | Supports and loads are scoped to the intended entities. |
| Solve | Solution status is completed; messages, solver output, and result files are inspected before retry. |
| Results | Result objects exist and extracted values are finite and physically plausible. |

Use screenshots for human review, but use structured inspect targets and numeric
checks for acceptance.
