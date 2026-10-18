---
name: hypermesh-sim
description: Use when preparing meshes or model decks in HyperMesh through a visible sim session, especially when a human engineer should watch and inspect each agent step.
---

# hypermesh-sim

Use this skill for visible, human-in-the-loop HyperMesh work through `sim`.
The goal is a shared mesh-preparation loop, not unattended headless execution.

## Preferred Loop

1. Check availability:

```powershell
uv run sim check hypermesh
```

2. Connect with a visible desktop session:

```powershell
uv run sim connect --solver hypermesh --ui-mode gui --workspace .\workspace
uv run sim inspect session.health
```

3. Execute one bounded step at a time:

```powershell
uv run sim exec --file .\step.py --label mesh-step
uv run sim inspect last.result
uv run sim inspect hypermesh.workspace.files
```

4. Visually inspect the GUI after meaningful actions: import, cleanup, mesh
generation, quality checks, load/property assignment, and export.

5. Save or export checkpoints before moving to the next layer.

## Snippet Rules

- Keep each snippet small enough to review from `last.result`.
- Write a JSON-serializable object to `_result` when possible.
- Prefer numeric acceptance data: node/element counts, quality criteria,
  exported file paths, warnings, and failed entity counts.
- Do not rely on process exit alone as engineering acceptance.
- If the human changes the GUI, inspect health/results again before continuing.

## Expected Result Shape

Useful snippets set `_result`, for example:

```python
_result = {
    "ok": True,
    "stage": "mesh-quality",
    "nodes": 1200,
    "elements": 950,
    "max_aspect": 4.2,
    "exported": r"C:\work\case\mesh.fem",
}
```

The plugin wraps snippets and returns `stdout`, `stderr`, `_result`, elapsed
time, and workspace artifacts through `uv run sim inspect last.result`.

## Hard Stops

- If `session.health.connected` is false, reconnect before making changes.
- If a GUI dialog appears, resolve it visibly before continuing.
- If a mesh step produces no counts, no export, and no quality data, treat it
  as incomplete even if the command returned successfully.
