# Debug failed Workbench exec

When `sim exec` or `sim run --solver workbench` fails, stop sending large
journals. Inspect the failure and the current project state, then retry with the
smallest focused journal.

## Triage

1. Inspect structured state:

   ```bash
   sim inspect session.health
   sim inspect last.result
   sim inspect workbench.project.identity
   sim inspect workbench.systems.summary
   ```

2. Classify the failure:

| Class | Typical signal | First check |
|---|---|---|
| Journal syntax | Syntax error or IronPython parse failure | Fix the journal only. |
| Missing template | Static Structural or other template not found | Inspect available templates or choose a supported workflow. |
| Missing cell | Model, Geometry, Setup, or Solution cell is unavailable | Inspect `workbench.systems.summary`. |
| SDK/fallback mismatch | SDK launch failed, RunWB2 fallback used | Check `session.health.backend`. |
| Stale project state | Cell status does not match expected step | Refresh/update one cell, then re-inspect. |
| Handoff mismatch | Mechanical opens a different or empty model | Re-check Workbench Model cell and Mechanical project identity. |

3. Retry with one bounded repair step. Do not rebuild the full project unless
   the current project state is intentionally disposable.

## Minimal retry pattern

Write a compact JSON result through the Workbench result-file convention:

```python
import json, os, codecs
out = os.path.join(os.environ.get("TEMP", "C:/Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": True, "changed": "geometry_refreshed"}))
f.close()
```

Record repeated version-specific workarounds in `solver/<version>/notes.md`.
