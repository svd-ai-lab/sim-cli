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

## Install

```bash
pip install sim-plugin-mechanical
```

You can also install through sim-cli:

```bash
sim plugin install sim-plugin-mechanical
```

After installation, sim-cli auto-discovers the driver and bundled skill:

```bash
sim check mechanical
sim connect --solver mechanical --ui-mode gui
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
