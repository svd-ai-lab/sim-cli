# sim-plugin-autodeskfusion

Autodesk Fusion driver plugin for `sim`, focused on thin official-MCP access to
a visible Fusion desktop session. Fusion's Python API is available inside the
Fusion process, so this plugin discovers Autodesk's local MCP server, lists its
tools, and calls the execute-capable tool instead of installing a custom add-in
bridge.

Autodesk Fusion is commercial vendor software. This plugin does not bundle
Fusion binaries, Autodesk API stubs, installers, sample projects, licenses, or
activation material; users must install and license Fusion separately. See
[LICENSE-NOTICE.md](LICENSE-NOTICE.md).

## Install

For agent projects, install sim-cli-core and the Autodesk Fusion plugin in the
project environment:

```powershell
uv init  # only if this is not already a uv project
uv add sim-cli-core "sim-plugin-autodeskfusion @ git+https://github.com/svd-ai-lab/sim-plugin-autodeskfusion@main"
uv run sim plugin sync-skills --target .agents/skills --copy
uv run sim check autodeskfusion
uv run sim plugin doctor autodeskfusion --deep
```

For Claude Code, sync the bundled skill to `.claude/skills` instead:

```powershell
uv run sim plugin sync-skills --target .claude/skills --copy
```

Without uv, create and activate a venv, then install `sim-cli-core` plus this
plugin with `python -m pip`:

```powershell
python -m pip install sim-cli-core "sim-plugin-autodeskfusion @ git+https://github.com/svd-ai-lab/sim-plugin-autodeskfusion@main"
```

## Scope

- Detect local Fusion installs without launching Fusion.
- Probe Autodesk Fusion's official local MCP endpoint.
- Use MCP `initialize`, `tools/list`, and `tools/call` through the official MCP
  Python SDK.
- Execute Python scripts/snippets through the discovered execute-capable MCP
  tool.
- Keep `sim` optional: direct MCP calls are often the better exploration
  primitive, while `sim connect/exec/inspect` adds session bookkeeping and
  standard logs when useful.

The driver does not provide a headless Fusion solver and does not automate
Autodesk sign-in, cloud-save prompts, or licensing flows.

## MCP Endpoint

Autodesk documents the default local endpoint as:

```text
http://127.0.0.1:27182/mcp
```

If that port is occupied or Fusion selected another loopback port, set:

```powershell
$env:SIM_AUTODESKFUSION_MCP_URL = "http://127.0.0.1:55484/mcp"
```

You can also pass the endpoint only for a `sim` session:

```powershell
uv run sim connect --solver autodeskfusion --driver-option mcp_url=http://127.0.0.1:55484/mcp
```

## Example

```powershell
uv run sim connect --solver autodeskfusion
uv run sim inspect mcp.tools
uv run sim exec --file path\to\fusion_script.py --label fusion-probe
uv run sim inspect last.result
uv run sim disconnect
```

Scripts should be valid Fusion Python and usually expose a `run` entrypoint:

```python
import adsk.core
import adsk.fusion


def run(_context: str):
    app = adsk.core.Application.get()
    print(app.activeDocument.name if app.activeDocument else "no document")
```

If a script writes JSON to `SIM_AUTODESKFUSION_OUT`, the driver reports that
file as a structured artifact alongside the raw MCP tool result.

## Develop

```bash
git clone https://github.com/svd-ai-lab/sim-plugin-autodeskfusion
cd sim-plugin-autodeskfusion
uv sync --extra test
uv run sim plugin list
uv run sim check autodeskfusion
uv run --extra test pytest --basetemp .pytest_basetemp/local -q
uv build
```

Live integration checks require an interactive desktop session with Fusion open
and its official MCP server enabled.

## License

Apache-2.0 for the plugin code itself. See [LICENSE](LICENSE) and
[LICENSE-NOTICE.md](LICENSE-NOTICE.md).
