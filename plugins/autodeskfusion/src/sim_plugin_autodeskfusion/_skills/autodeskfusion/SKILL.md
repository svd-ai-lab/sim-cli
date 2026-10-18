---
name: autodeskfusion
description: Use when working with Autodesk Fusion or Fusion 360 through its official local MCP server, including live desktop session inspection, Design workspace model edits, document/body/sketch probes, export checks, and short in-process `adsk` Python scripts. Do not import `adsk` from host Python; execute Fusion API code inside Fusion through MCP or the sim autodeskfusion connector.
---

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
   Fusion-owned loopback listeners. `http://127.0.0.1:55484/mcp` is a common
   Fusion MCP URL observed on this machine, but do not hardcode it: the port can
   change across machines, Fusion versions, or local service conflicts.
3. Call MCP `initialize`, then `tools/list`. Let the returned tool schemas
   guide the next call; do not assume a fixed port or permanent tool list.
4. For Python execution, prefer the discovered execute-capable tool, commonly
   `fusion_mcp_execute`. Send scripts with a `def run(_context: str)` entrypoint
   unless the current tool schema says otherwise.
5. After GUI-visible mutations, capture or request visual evidence before the
   next edit.

## Stability Lessons

- Treat Fusion as a strict CAD kernel, not a tolerant visualizer. Meshes,
  renderers, and preview tools may display geometry that Fusion rejects as an
  invalid B-rep, especially near self-intersections, tight curvature, tiny
  clearances, or very dense paths.
- Increase complexity step by step. Start with the smallest inspectable
  primitive, then add bodies, repeats, detail, and export steps incrementally.
  After changing a path, size, topology, or API method, return to a small smoke
  case before rebuilding the full model.
- Run cheap host-side gates before asking Fusion to create solids: bounds,
  units, entity counts, clearance checks, curvature or feature-size checks, and
  expected export targets. If a gate shows the requested solid is geometrically
  impossible or marginal, record the limitation instead of forcing the operation.
- For near-contact geometry, record explicit contact diagnostics rather than
  relying on screenshots: nominal feature size, minimum relevant distance,
  clearance margin, and the sampled/contact pair. Treat intended touching as a
  small positive CAD margin when the downstream kernel is sensitive to exact
  tangency.
- If a primary Fusion feature constructor fails, try a semantically equivalent
  native construction only when it preserves the same topology, dimensions, and
  source geometry. Record both the fallback method and the original failure in
  metadata so the fallback remains auditable.
- Separate model creation from heavyweight export. When a full STEP/archive
  export risks freezing Fusion, first create the model with export disabled,
  capture review screenshots or diagnostic markers, then export smaller smoke
  cases or retry the full export only after the geometry is accepted.
- Use short MCP/client timeouts for exploratory calls. If a step fails or times
  out, reduce scope or switch to a simpler representation; do not keep retrying
  heavy operations with longer timeouts.
- Keep generated Fusion documents under control. Before creating another
  automation document, close or save prior generated documents as appropriate,
  and avoid accumulating multiple generated projects in the desktop session.
  Treat human-owned unsaved work conservatively.
- Prefer scripts with explicit runtime options supplied by context or
  environment variables, such as geometry mode, detail level, sample count,
  export mode, output tag, and diagnostic simplifications. Do not bake local
  paths, ports, sizes, or temporary settings into reusable scripts.
- If Fusion becomes unresponsive, stop sending more MCP calls. Inspect the
  process state, restart Fusion only when appropriate, then rediscover the MCP
  endpoint and resume from the smallest passing step.
- Preserve metadata with every export: sources, units, coordinate mapping,
  build mode, simplifications, bounds, object names/counts, output files, and
  failure messages.

## sim Workflow

From a project environment with the plugin installed:

```powershell
uv run sim check autodeskfusion
uv run sim connect --solver autodeskfusion
uv run sim exec --file path\to\fusion_script.py --label probe
uv run sim inspect mcp.tools
uv run sim disconnect
```

The `mcp_url` option is optional when discovery can find the endpoint. Use it
when discovery fails or another local service occupies Autodesk's documented
default port, for example `--driver-option
mcp_url=http://127.0.0.1:55484/mcp` after verifying that port belongs to Fusion
on the current machine.

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
