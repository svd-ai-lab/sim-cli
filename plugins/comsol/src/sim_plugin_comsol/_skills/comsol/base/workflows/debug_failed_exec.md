# Debug failed exec

When `sim exec` fails, stop generating new full scripts. Inspect the
failure and the live model state, then retry with the smallest patch.

## Triage

1. Inspect the structured result:

   ```bash
   sim inspect last.result
   ```

2. Classify the failure:

   | Class | Typical signal | First check |
   |---|---|---|
   | Python issue | Syntax error, import error, name error | Fix the snippet only. |
   | Missing tag | Unknown component, physics, feature, material, or study tag | List parent `tags()`. |
   | Missing property | COMSOL rejects `set(...)` key | Inspect `properties()` on the live node. |
   | Empty selection | Solve or feature build fails after geometry changes | Inspect named selections and selected entities. |
   | Geometry failure | `geom.run()` fails | Inspect geometry feature order and entity dimensions. |
   | Mesh failure | Mesh build fails or produces impossible size | Inspect geometry validity and local size features. |
   | Solver failure | Study fails after setup looked valid | Inspect physics/material consistency and run smaller probes. |
   | Module missing | Feature type not found, docs absent, license issue | Check `session.health` and choose a capability fallback path. |

3. Inspect live model state:

   ```bash
   sim inspect comsol.model.describe_text
   ```

4. Inspect the suspicious node:

   ```bash
   sim inspect comsol.node.properties:<tag-or-dot-path>
   ```

5. If the inspect target is unavailable, use the raw Java snippets in
   `base/reference/java_api_patterns.md`.

6. Search local COMSOL docs only after live introspection does not answer
   the question:

   ```bash
   uv run --project <skill>/doc-search sim-comsol-doc search "2-3 keywords" --module <module>
   ```

7. Retry with a small patch. Do not re-run a full builder unless the
   model state is intentionally being rebuilt from scratch.

## Minimal retry pattern

Return enough information for the next decision:

```python
try:
    # one targeted fix or one read-only probe
    _result = {"ok": True, "changed": "comp1.ht.hf1"}
except Exception as exc:
    _result = {
        "ok": False,
        "type": type(exc).__name__,
        "message": str(exc),
    }
    raise
```

## Good repair behavior

- Keep the current session unless it is corrupted.
- Save a `.mph` checkpoint before risky rebuilds.
- Prefer checking parent tags over guessing child tags.
- Prefer inspecting a node over trying alternate property names.
- Record repeated version-specific workarounds in `solver/<version>/notes.md`.
