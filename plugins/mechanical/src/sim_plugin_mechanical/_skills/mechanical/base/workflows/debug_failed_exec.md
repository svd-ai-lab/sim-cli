# Debug failed Mechanical exec

When `sim exec` fails, stop sending full setup scripts. Inspect the failure and
the live Mechanical state, then retry with the smallest focused snippet.

## Triage

1. Inspect structured state:

   ```bash
   sim inspect session.health
   sim inspect last.result
   sim inspect mechanical.project.identity
   sim inspect mechanical.model.summary
   ```

2. Classify the failure:

| Class | Typical signal | First check |
|---|---|---|
| IronPython issue | Syntax error, missing enum, unsupported language feature | Fix the snippet only. |
| Empty geometry | Body count is zero | Return to Workbench/geometry import before setup. |
| Empty selection | Support/load exists but solve reports missing scoping | Inspect selection dimensions and entity IDs. |
| Mesh failure | Mesh count missing or mesh generation fails | Inspect geometry validity and mesh controls. |
| Solve failure | Solver output or `.err` file appears | Inspect solver output and simplify setup. |
| Result failure | Result object exists but value extraction fails | Inspect solution status and result object type. |
| GUI mismatch | SDK state changes but no visible window is found | Inspect `session.health` and reconnect in GUI mode if needed. |

3. Probe only the suspicious target:

   ```bash
   sim inspect mechanical.object.properties:mesh
   sim inspect mechanical.object.properties:geometry
   sim inspect mechanical.object.properties:analysis:0
   sim inspect mechanical.object.properties:solution:0
   ```

4. Retry with one bounded repair step. Do not rebuild the whole model unless
   the current state is intentionally disposable.

## Result return rule

End every snippet with an ASCII-safe JSON expression:

```python
import json
result = {"ok": True, "changed": "fixed_support"}
json.dumps(result)
```

Avoid returning raw `.Name`, project path, or localized strings. Return counts,
booleans, tags that you created yourself, or sanitized strings.
