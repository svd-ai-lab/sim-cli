# sim-plugin-hypermesh

Private HyperMesh plugin for `sim-cli`.

This package lets `sim` discover a locally available HyperMesh installation,
open a visible desktop session, submit bounded Python snippets, and report
session health and run results back to an agent. It is intended for
human-in-the-loop mesh preparation where an engineer can watch the GUI, inspect
state, and correct course between agent steps.

This repository contains only the plugin code and bundled agent guidance. It
does not include third-party software.

## Install

From a private checkout:

```powershell
uv add --editable C:\Users\jiwei\Documents\GitHub\sim-plugin-hypermesh
uv run sim plugin sync-skills --target .agents/skills --copy
uv run sim check hypermesh
```

## Agent Loop

```powershell
uv run sim connect --solver hypermesh --ui-mode gui --workspace .\workspace
uv run sim inspect session.health
uv run sim exec --file .\step.py --label mesh-step-1
uv run sim inspect last.result
uv run sim inspect hypermesh.workspace.files
uv run sim disconnect
```

`ui_mode=gui` is required. Mesh work is visual and stateful, so the plugin
keeps the desktop session first-class instead of pretending it is a headless
batch solver.

## Development

```powershell
uv sync --extra test
New-Item -ItemType Directory -Force .pytest_basetemp | Out-Null
uv run pytest tests -q --basetemp .pytest_basetemp\local
uv run sim plugin doctor hypermesh --deep
```

## License

Apache-2.0 for this plugin code. Product names remain the property of their
respective owners.
