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
| Solve failure | `Solution.Status` is `SolveRequired`, `NotSolved`, or `Failed`; solver output or `.err` file appears | Inspect `mechanical.messages`, solver files, and setup completeness before retry. |
| Result failure | Result object exists but value extraction fails, or a GUI post-processing dialog appears | Inspect solution status, `mechanical.messages`, and live result methods from `mechanical.capabilities`. |
| Long-running hang | `sim exec` is blocked, but the GUI may still be updating | Use `sim screenshot` from another terminal/thread to inspect progress, popups, or stalled solver startup. |
| GUI mismatch | SDK state changes but no visible window is found | Inspect `session.health` and reconnect in GUI mode if needed. |

3. Probe only the suspicious target:

   ```bash
   sim inspect mechanical.object.properties:mesh
   sim inspect mechanical.object.properties:geometry
   sim inspect mechanical.object.properties:analysis:0
   sim inspect mechanical.object.properties:solution:0
   sim inspect mechanical.capabilities:analysis:0
   sim inspect mechanical.messages
   ```

4. Retry with one bounded repair step. Do not rebuild the whole model unless
   the current state is intentionally disposable.

If a method is missing or behaves differently from memory, search official
PyMechanical scripting docs/examples, then verify the documented method in the
live `mechanical.capabilities` output. Add generic discovery or validation
rules to the skill, not a one-off workaround for the current model.

For interrupted long runs, first determine whether the solver GUI/process is
still alive. Capture a screenshot if a window remains, then clean up only the
process tree created by the current run before retrying.

## Result return rule

End every snippet with an ASCII-safe JSON expression:

```python
import json
result = {"ok": True, "changed": "fixed_support"}
json.dumps(result)
```

Avoid returning raw `.Name`, project path, or localized strings. Return counts,
booleans, tags that you created yourself, or sanitized strings.
