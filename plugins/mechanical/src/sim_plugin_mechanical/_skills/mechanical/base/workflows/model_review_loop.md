# Mechanical model review loop

Use this loop for every non-trivial Mechanical setup, solve, or result
extraction task. Mechanical state is layered: a solve failure often comes from
geometry, scoping, mesh, or boundary-condition state created earlier.

## Loop

1. Inspect `sim inspect session.health`.
2. Inspect `sim inspect mechanical.project.identity`.
3. Inspect `sim inspect mechanical.model.summary`.
4. Execute one bounded IronPython snippet.
5. Inspect `sim inspect last.result`.
6. Re-inspect `mechanical.model.summary`.
7. In GUI mode, capture or review a screenshot after significant visible tree
   changes.
8. Continue only when structured state and visual state match the intended
   setup.

## Checkpoints

| Layer | Expected evidence |
|---|---|
| Project | Health is ok; project identity names an active model state; checkpoint readiness is understood. |
| Analysis | Expected analysis type exists before adding setup objects. |
| Geometry | Body count is nonzero before applying supports, loads, mesh controls, or results. |
| Selections | Named selections or selection info objects are non-empty and match the intended entity dimension. |
| Mesh | Mesh node/element counts are plausible for the geometry. |
| Setup | Supports and loads are scoped to the intended entities. |
| Solve | Solver output and result files are detected; errors are inspected before retry. |
| Results | Result objects exist and extracted values are finite and physically plausible. |

Use screenshots for human review, but use structured inspect targets and numeric
checks for acceptance.
