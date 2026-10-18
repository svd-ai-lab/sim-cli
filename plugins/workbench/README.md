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
uv run sim connect --solver workbench --ui-mode gui
uv run sim inspect session.health
uv run sim exec --file step.wbjn
uv run sim inspect workbench.systems.summary
```

The SDK path is preferred because it keeps state across steps and lets the
agent inspect Workbench state between bounded journal snippets.

### 2. RunWB2 fallback

Use this when the SDK is unavailable or incompatible:

```powershell
uv run sim run --solver workbench path/to/journal.wbjn
```

RunWB2 is reliable for one-shot journals, but it should not be treated as a
rich live session. Inspect the JSON result written by the journal and save a
project checkpoint before handing off to another solver.

### 3. Workbench-to-Mechanical handoff

Use Workbench for cells 1-3: Engineering Data, Geometry, and Model. Use
Mechanical for cells 4-6: setup, solution, and results. Before handoff, inspect:

```powershell
uv run sim inspect workbench.project.identity
uv run sim inspect workbench.systems.summary
```

The Workbench side should have a project checkpoint and a refreshed Model cell.
The Mechanical side should confirm the expected analysis tree before adding
loads, supports, mesh controls, solve settings, or result objects.

## Prerequisites

Install these before asking an agent to use this plugin:

- Python 3.10 or newer.
- [uv](https://docs.astral.sh/uv/) for Python environment and package installs.
- [git](https://git-scm.com/) when installing from GitHub source refs.
- A project Python environment where sim-cli-core can be installed.
- A local Ansys Workbench installation compatible with PyWorkbench or RunWB2.

The plugin does not include Workbench or vendor SDK binaries. It installs the
Python adapter and its Python dependencies only.

## Install

For agent projects, install sim-cli-core and the Workbench plugin in the
project environment:

```powershell
uv init  # only if this is not already a uv project
uv add sim-cli-core sim-plugin-workbench
uv run sim plugin sync-skills --target .agents/skills --copy
uv run sim check workbench
uv run sim plugin doctor workbench --deep
```

For Claude Code, sync the bundled skill to `.claude/skills` instead:

```powershell
uv run sim plugin sync-skills --target .claude/skills --copy
```

For a reproducible agent run, pin a commit SHA:

```powershell
uv add sim-cli-core "git+https://github.com/svd-ai-lab/sim-plugin-workbench.git@<commit-sha>"
```

If your environment uses SSH authentication:

```powershell
uv add sim-cli-core "git+ssh://git@github.com/svd-ai-lab/sim-plugin-workbench.git@<commit-sha>"
```

`uv run sim ...` runs sim from this project environment, so it sees this
project's plugins. Without uv, create and activate a venv, then install
`sim-cli-core` plus this plugin with `python -m pip`.

## Verify Install

After installation, sim-cli should auto-discover the driver and bundled skill:

```powershell
uv run sim check workbench
```

If `uv run sim check workbench` reports that Workbench itself is unavailable, first
confirm the Python package installed correctly, then fix the local Workbench or
SDK prerequisites.

## Connect And Inspect Health

Use a visible Workbench session when an agent needs human-visible project state:

```powershell
uv run sim connect --solver workbench --ui-mode gui
uv run sim inspect session.health
uv run sim inspect workbench.project.identity
uv run sim inspect workbench.systems.summary
```

Use one-shot RunWB2 execution only for bounded journals:

```powershell
uv run sim run --solver workbench path/to/journal.wbjn
```

## Common Agent Workflow

1. Choose persistent SDK session, RunWB2 one-shot, or handoff workflow.
2. Inspect `session.health`.
3. Run one bounded journal step.
4. Inspect `last.result` and `workbench.systems.summary`.
5. Save or checkpoint the project before risky edits or solver handoff.
6. Stop if a parsed journal result reports `ok=false`; inspect the diagnostic
   before retrying a larger journal.

## Workbench-To-Mechanical Handoff

Workbench owns Engineering Data, Geometry, and Model cells. Mechanical owns
setup, solve, and results. Before handoff:

```powershell
uv run sim inspect workbench.project.identity
uv run sim inspect workbench.systems.summary
```

Continue only when the expected Workbench system exists, the Model cell is
available, and the project has a checkpoint suitable for downstream solver
work.

## Update Or Uninstall

Update the published package:

```powershell
uv add --upgrade sim-plugin-workbench
```

Update from the latest GitHub `main` branch:

```powershell
uv add "git+https://github.com/svd-ai-lab/sim-plugin-workbench.git@main"
```

Uninstall:

```powershell
uv remove sim-plugin-workbench
```

## Troubleshooting

- `sim` command not found: run commands through `uv run sim ...` or activate
  the venv that contains sim-cli-core.
- Driver not discovered: reinstall the plugin and run `uv run sim check workbench`.
- Workbench launch fails: inspect `session.health` and confirm local Workbench
  prerequisites outside sim-cli.
- A journal appears to run but no system is created: inspect `last.result`; a
  parsed `ok=false` result is treated as a failed step.

## Agent quickstart

Give an agent this instruction when the task is about Workbench:

```text
Use the bundled Workbench skill from sim-plugin-workbench. First identify
whether the task needs a persistent SDK session, a RunWB2 one-shot journal, or
a Workbench-to-Mechanical handoff. For persistent work, connect with
`uv run sim connect --solver workbench --ui-mode gui`, then inspect `session.health`,
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
