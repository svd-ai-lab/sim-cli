# sim-plugin-workbench

Use Codex, Claude Code, or another AI agent to orchestrate
[Ansys Workbench](https://www.ansys.com/products/ansys-workbench) projects from
the workflow you already use.

`sim-plugin-workbench` gives an agent practical Workbench control paths:
create and update analysis systems, run Workbench journals, inspect live session
health, summarize systems and cells, manage project checkpoints, and hand the
Model cell off to solver-specific plugins such as Mechanical.

The Workbench application and SDK are not bundled. Bring your own Workbench
installation. See [LICENSE-NOTICE.md](LICENSE-NOTICE.md).

## What an agent can do with Workbench

- Create or update Workbench analysis systems through journals.
- Keep Engineering Data, Geometry, and Model cells organized before solver work.
- Use a persistent PyWorkbench session when the SDK is available.
- Fall back to RunWB2 journal execution when the SDK path is unavailable.
- Inspect session health, UI capabilities, project identity, and system/cell
  state before continuing a workflow.
- Prepare a clean handoff to Mechanical for setup, solve, and result extraction.

## Choose the right Workbench workflow

### 1. Persistent SDK session

Use this for repeatable agent-driven orchestration:

```powershell
sim connect --solver workbench --ui-mode gui
sim inspect session.health
sim exec --file step.wbjn
sim inspect workbench.systems.summary
```

The SDK path is preferred because it keeps state across steps and lets the
agent inspect Workbench state between bounded journal snippets.

### 2. RunWB2 fallback

Use this when the SDK is unavailable or incompatible:

```powershell
sim run --solver workbench path/to/journal.wbjn
```

RunWB2 is reliable for one-shot journals, but it should not be treated as a
rich live session. Inspect the JSON result written by the journal and save a
project checkpoint before handing off to another solver.

### 3. Workbench-to-Mechanical handoff

Use Workbench for cells 1-3: Engineering Data, Geometry, and Model. Use
Mechanical for cells 4-6: setup, solution, and results. Before handoff, inspect:

```powershell
sim inspect workbench.project.identity
sim inspect workbench.systems.summary
```

The Workbench side should have a project checkpoint and a refreshed Model cell.
The Mechanical side should confirm the expected analysis tree before adding
loads, supports, mesh controls, solve settings, or result objects.

## Install

```bash
pip install sim-plugin-workbench
```

You can also install through sim-cli:

```bash
sim plugin install sim-plugin-workbench
```

After installation, sim-cli auto-discovers the driver and bundled skill:

```bash
sim check workbench
sim run --solver workbench path/to/journal.wbjn
```

## Agent quickstart

Give an agent this instruction when the task is about Workbench:

```text
Use the bundled Workbench skill from sim-plugin-workbench. First identify
whether the task needs a persistent SDK session, a RunWB2 one-shot journal, or
a Workbench-to-Mechanical handoff. For persistent work, connect with
`sim connect --solver workbench --ui-mode gui`, then inspect `session.health`,
`workbench.project.identity`, and `workbench.systems.summary`. Execute one
bounded journal step at a time, inspect the result, and save or update a
project checkpoint before handing the Model cell to Mechanical.
```

The bundled skill entry point is:

```text
src/sim_plugin_workbench/_skills/workbench/SKILL.md
```

## How it relates to sim-cli

`sim-plugin-workbench` extends [sim-cli](https://github.com/svd-ai-lab/sim-cli).
sim-cli provides the common agent runtime surface (`connect`, `exec`, `inspect`,
`run`, `screenshot`), while this plugin supplies Workbench detection, journal
execution, persistent session handling, and bundled Workbench agent guidance.

The plugin registers three entry-point groups:

```toml
[project.entry-points."sim.drivers"]
workbench = "sim_plugin_workbench:WorkbenchDriver"

[project.entry-points."sim.skills"]
workbench = "sim_plugin_workbench:skills_dir"

[project.entry-points."sim.plugins"]
workbench = "sim_plugin_workbench:plugin_info"
```

## Develop

```bash
git clone https://github.com/svd-ai-lab/sim-plugin-workbench
cd sim-plugin-workbench
uv sync
uv run pytest tests -m "not integration"
```

End-to-end tests require a local Workbench installation and are skipped unless
their prerequisites are available.

## License

Apache-2.0. See [LICENSE](LICENSE) and [LICENSE-NOTICE.md](LICENSE-NOTICE.md).
