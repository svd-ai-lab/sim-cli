# Model review loop

Use this loop for every non-trivial COMSOL model. COMSOL state is
layered; a solver error often comes from a geometry, selection, material,
or physics mistake created many steps earlier.

## Loop

0. Establish or verify model identity, workdir, and checkpoint target.
1. Execute one bounded modeling step.
2. Inspect `sim inspect last.result`.
3. Inspect `sim inspect comsol.model.identity` when available.
4. Inspect the live model with `sim inspect comsol.model.describe_text`
   when available.
5. Inspect suspicious nodes with
   `sim inspect comsol.node.properties:<tag-or-dot-path>` or a raw Java
   fallback snippet.
6. Compare the live model to the intended state below.
7. Save or update the checkpoint `.mph` after each passed major layer.
8. Continue only after the checkpoint passes.

## Checkpoints

| Layer | Expected evidence |
|---|---|
| Identity | Active model tag and bound model tag are known; model has a title/label; serious work has a saved `.mph` or database location; `model.modelPath(...)` includes needed input/model folders; the working folder contains related inputs, scripts, outputs, and logs. |
| Geometry | Expected component exists; geometry sequence has expected features; named selections exist for later physics; saved `.mph` artifact opens if Desktop review is needed. |
| Materials | Material tags exist; each material has a non-empty domain selection; critical property groups are present. |
| Physics | Physics interfaces exist; required domain and boundary features exist; feature selections are non-empty and match the intended entity dimension. |
| Mesh | Mesh sequence exists; build completes; mesh statistics or saved artifact probes look plausible for the geometry size. |
| Study | Study tag exists; study type matches the physics; parametric sweeps use explicit named parameters. |
| Solve | `last.result` is ok; solver log has no hidden warnings that invalidate the run; numerical probes are finite. |
| Results | Datasets, plot groups, and numerical evaluation nodes exist; acceptance checks use numeric probes, not screenshots. |

## Acceptance style

Prefer numeric acceptance:

- scalar probe values with tolerances
- conservation residuals
- monotonic trends over a parameter sweep
- sign checks for fluxes, rates, or overpotentials
- location checks for maxima/minima when physically meaningful

Screenshots are useful for human review, but they are not the primary
acceptance mechanism.

## Saved artifact review

When a workflow saves `.mph` files after major steps, use archive
inspection for offline confirmation:

```python
from sim_plugin_comsol.lib import inspect_mph, mph_diff

before = inspect_mph("before.mph")
after = inspect_mph("after.mph")
delta = mph_diff("before.mph", "after.mph")
```

Use live introspection for the current session and archive inspection for
saved artifacts.
