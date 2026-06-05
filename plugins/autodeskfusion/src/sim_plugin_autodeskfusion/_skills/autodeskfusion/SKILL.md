# Autodesk Fusion via MCP

Use this skill when working with Autodesk Fusion through its official local MCP
server. Fusion's `adsk` Python API runs inside the Fusion desktop process, so
prefer short, inspectable MCP calls against the live desktop session.

## Tool Choice

Use the narrowest useful primitive:

- Direct MCP: best for exploration, tool/resource discovery, quick Fusion API
  probes, and one-off scripts when the agent can call the MCP endpoint itself.
- `sim connect/exec/inspect`: use when session history, shared `sim serve`
  access, standard logs, or plugin discovery make the workflow easier to
  resume.
- Host Python: use for saved file parsing, JSON/report post-processing, and
  acceptance checks that do not need Fusion's in-process `adsk` modules.

Do not import `adsk` from host Python. If a task needs `adsk`, execute that
code in Fusion through MCP.

## MCP Workflow

1. Keep Fusion open and visible. Human-owned dialogs such as sign-in, account
   selection, cloud-save prompts, and first-run setup stay outside automation.
2. Discover the endpoint. Prefer `SIM_AUTODESKFUSION_MCP_URL` when provided;
   otherwise try Autodesk's documented default and, if needed, inspect local
   Fusion-owned loopback listeners.
3. Call MCP `initialize`, then `tools/list`. Let the returned tool schemas
   guide the next call; do not assume a fixed port or permanent tool list.
4. For Python execution, prefer the discovered execute-capable tool, commonly
   `fusion_mcp_execute`. Send scripts with a `def run(_context: str)` entrypoint
   unless the current tool schema says otherwise.
5. After GUI-visible mutations, capture or request visual evidence before the
   next edit.

## sim Workflow

From a project environment with the plugin installed:

```powershell
uv run sim check autodeskfusion
uv run sim connect --solver autodeskfusion --driver-option mcp_url=http://127.0.0.1:55484/mcp
uv run sim exec --file path\to\fusion_script.py --label probe
uv run sim inspect mcp.tools
uv run sim disconnect
```

The `mcp_url` option is optional when discovery can find the endpoint. Use it
when another local service occupies Autodesk's documented default port.

## Script Pattern

Keep scripts small and reviewable:

```python
import json
import os
import adsk.core
import adsk.fusion


def run(_context: str):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    result = {
        "ok": design is not None,
        "document_name": app.activeDocument.name if app.activeDocument else None,
    }
    out = os.environ.get("SIM_AUTODESKFUSION_OUT")
    if out:
        with open(out, "w", encoding="utf-8") as handle:
            json.dump(result, handle)
    return result
```

## Boundaries

- Good targets: Design workspace model edits, document/body/sketch inspection,
  export probes, and visible co-editing.
- Do not assume Simulation workspace solve automation exists until a real
  `adsk.sim` or MCP probe proves the current Fusion version supports it.
- Keep cloud saves, account state, and vendor licensing decisions human-owned.
