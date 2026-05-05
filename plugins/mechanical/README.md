# sim-plugin-mechanical

Use Codex, Claude Code, or another AI agent to work with
[Ansys Mechanical](https://www.ansys.com/products/structures/ansys-mechanical)
models through [sim-cli](https://github.com/svd-ai-lab/sim-cli).

`sim-plugin-mechanical` gives an agent practical Mechanical control paths:
drive a live Mechanical GUI through PyMechanical, inspect runtime health, add
loads/supports/solution objects, solve, summarize the model tree, and extract
or describe result artifacts.

The Mechanical application and SDK are not bundled. Bring your own Mechanical
installation. See [LICENSE-NOTICE.md](LICENSE-NOTICE.md).

This plugin is for Ansys Mechanical, not Dassault SIMULIA Abaqus. Use the
Abaqus plugin for Abaqus decks and Abaqus/CAE scripts.

## What an agent can do with Mechanical

- Mutate a live Mechanical model through Mechanical's IronPython API.
- Keep GUI-visible work synchronized with SDK state in `gui` mode.
- Inspect `session.health`, `mechanical.project.identity`, and
  `mechanical.model.summary` before each bounded setup or solve step.
- Add and inspect supports, loads, mesh state, solution objects, and result
  objects.
- Detect solver/result artifacts such as result files, solver output, error
  files, and exported CSV data.
- Continue a Workbench Static Structural handoff once the Model cell is ready.

## Choose the right Mechanical workflow

### 1. Live GUI session

Use this when the user wants to watch or review the Mechanical tree while the
agent works:

```powershell
sim connect --solver mechanical --ui-mode gui
sim inspect session.health
sim exec --file setup_step.py
sim inspect mechanical.model.summary
```

In GUI mode, Mechanical's visible window and PyMechanical client mutate the
same in-memory model. Use screenshots for visual review, but use structured
inspect targets for acceptance decisions.

### 2. Headless smoke or batch-style checks

Use `--ui-mode no_gui` only when visual confirmation is not needed:

```powershell
sim connect --solver mechanical --ui-mode no_gui
```

Headless mode is faster but screenshot confirmation is unavailable. Inspect
`session.health.ui_capabilities` before relying on GUI observations.

### 3. Workbench handoff

Workbench owns Engineering Data, Geometry, and Model. Mechanical owns setup,
solve, and results. Before applying Mechanical loads or supports, inspect:

```powershell
sim inspect mechanical.project.identity
sim inspect mechanical.model.summary
```

Continue only when the expected analysis exists and the geometry/body state is
non-empty.

## Prerequisites

Install these before asking an agent to use this plugin:

- Python 3.10 or newer.
- [uv](https://docs.astral.sh/uv/) for Python environment and package installs.
- [git](https://git-scm.com/) when installing from GitHub source refs.
- sim-cli or a project environment where sim-cli can be installed.
- A local Ansys Mechanical installation compatible with PyMechanical.

The plugin does not include Mechanical or vendor SDK binaries. It installs the
Python adapter and its Python dependencies only.

## Install

For most users and agents, install the latest published PyPI version:

```powershell
uv pip install sim-plugin-mechanical
```

PyPI releases are intentionally infrequent. For quick testing of the current
source branch, install from GitHub:

```powershell
uv pip install "git+https://github.com/svd-ai-lab/sim-plugin-mechanical.git@main"
```

For a reproducible agent run, pin a commit SHA:

```powershell
uv pip install "git+https://github.com/svd-ai-lab/sim-plugin-mechanical.git@<commit-sha>"
```

If your environment uses SSH authentication:

```powershell
uv pip install "git+ssh://git@github.com/svd-ai-lab/sim-plugin-mechanical.git@<commit-sha>"
```

## Verify Install

After installation, sim-cli should auto-discover the driver and bundled skill:

```powershell
sim check mechanical
```

If `sim check mechanical` reports that Mechanical itself is unavailable, first
confirm the Python package installed correctly, then fix the local Mechanical or
SDK prerequisites.

## Connect And Inspect Health

Use GUI mode for agent-visible Mechanical workflows:

```powershell
sim connect --solver mechanical --ui-mode gui
sim inspect session.health
sim inspect mechanical.project.identity
sim inspect mechanical.model.summary
```

Use headless mode only for non-visual smoke checks:

```powershell
sim connect --solver mechanical --ui-mode no_gui
```

## Common Agent Workflow

1. Connect in GUI mode unless the user explicitly wants headless mode.
2. Inspect `session.health`, `mechanical.project.identity`, and
   `mechanical.model.summary`.
3. Run one bounded IronPython snippet.
4. Inspect `last.result` and `mechanical.model.summary`.
5. Continue only when the model state matches the expected analysis, geometry,
   mesh, and result state.
6. Treat `mechanical.solve.not_completed` as a failed solve, even if the SDK
   transport returned successfully.

## Workbench-To-Mechanical Handoff

Workbench owns Engineering Data, Geometry, and Model cells. Mechanical owns
setup, solve, and results. Before applying loads or supports:

```powershell
sim inspect mechanical.project.identity
sim inspect mechanical.model.summary
```

Continue only when the expected analysis exists and geometry/body state is
non-empty.

## Update Or Uninstall

Update to the latest published PyPI version:

```powershell
uv pip install --upgrade sim-plugin-mechanical
```

Update from the latest GitHub `main` branch:

```powershell
uv pip install --upgrade "git+https://github.com/svd-ai-lab/sim-plugin-mechanical.git@main"
```

Uninstall:

```powershell
uv pip uninstall sim-plugin-mechanical
```

## Agent quickstart

Give an agent this instruction when the task is about Mechanical:

```text
Use the bundled Mechanical skill from sim-plugin-mechanical. Connect with
`sim connect --solver mechanical --ui-mode gui` unless the user explicitly
wants headless mode. Before every setup, solve, or result step, inspect
`session.health`, `mechanical.project.identity`, and
`mechanical.model.summary`. Run one bounded IronPython snippet at a time,
return JSON from the last expression, inspect `last.result`, and use screenshots
only as visual confirmation. If the model came from Workbench, confirm the
handoff before applying loads or supports.
```

The bundled skill entry point is:

```text
src/sim_plugin_mechanical/_skills/mechanical/SKILL.md
```

## How it relates to sim-cli

`sim-plugin-mechanical` extends sim-cli with the Mechanical-specific driver and
bundled Mechanical skill. sim-cli supplies the common runtime surface
(`connect`, `exec`, `inspect`, `run`, `screenshot`), while this plugin supplies
Mechanical detection, PyMechanical launch, IronPython execution, health checks,
model summaries, and result artifact diagnostics.

The plugin registers three entry-point groups:

```toml
[project.entry-points."sim.drivers"]
mechanical = "sim_plugin_mechanical:MechanicalDriver"

[project.entry-points."sim.skills"]
mechanical = "sim_plugin_mechanical:skills_dir"

[project.entry-points."sim.plugins"]
mechanical = "sim_plugin_mechanical:plugin_info"
```

## Troubleshooting

### Secure transport launch failures

Some solver builds require insecure loopback transport for PyMechanical. Set
`SIM_MECHANICAL_INSECURE_TRANSPORT=1` before starting the sim session if the
driver reports a secure-transport launch failure.

### Screenshot captures no Mechanical window

Use `sim inspect session.health`. If `ui_capabilities.screenshot_expected` is
false, the session is headless. If screenshot support is expected but no
matching window is found, reconnect in GUI mode and inspect the health payload
before mutating more state.

## Develop

```bash
git clone https://github.com/svd-ai-lab/sim-plugin-mechanical
cd sim-plugin-mechanical
uv sync
uv run pytest tests -m "not integration"
```

End-to-end tests require a local Mechanical installation and are skipped unless
their prerequisites are available.

## License

Apache-2.0. See [LICENSE](LICENSE) and [LICENSE-NOTICE.md](LICENSE-NOTICE.md).
