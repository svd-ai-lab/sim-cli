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

## Prerequisites

Install these before asking an agent to use this plugin:

- Python 3.10 or newer.
- [uv](https://docs.astral.sh/uv/) for Python environment and package installs.
- [git](https://git-scm.com/) when installing from GitHub source refs.
- sim-cli or a project environment where sim-cli can be installed.
- A local Ansys Workbench installation compatible with PyWorkbench or RunWB2.

The plugin does not include Workbench or vendor SDK binaries. It installs the
Python adapter and its Python dependencies only.

## Install

For most users and agents, install the latest published PyPI version:

```powershell
uv pip install sim-plugin-workbench
```

PyPI releases are intentionally infrequent. For quick testing of the current
source branch, install from GitHub:

```powershell
uv pip install "git+https://github.com/svd-ai-lab/sim-plugin-workbench.git@main"
```

For a reproducible agent run, pin a commit SHA:

```powershell
uv pip install "git+https://github.com/svd-ai-lab/sim-plugin-workbench.git@<commit-sha>"
```

If your environment uses SSH authentication:

```powershell
uv pip install "git+ssh://git@github.com/svd-ai-lab/sim-plugin-workbench.git@<commit-sha>"
```

## Verify Install

After installation, sim-cli should auto-discover the driver and bundled skill:

```powershell
sim check workbench
```

If `sim check workbench` reports that Workbench itself is unavailable, first
confirm the Python package installed correctly, then fix the local Workbench or
SDK prerequisites.

## Connect And Inspect Health

Use a visible Workbench session when an agent needs human-visible project state:

```powershell
sim connect --solver workbench --ui-mode gui
sim inspect session.health
sim inspect workbench.project.identity
sim inspect workbench.systems.summary
```

Use one-shot RunWB2 execution only for bounded journals:

```powershell
sim run --solver workbench path/to/journal.wbjn
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
sim inspect workbench.project.identity
sim inspect workbench.systems.summary
```

Continue only when the expected Workbench system exists, the Model cell is
available, and the project has a checkpoint suitable for downstream solver
work.

## Update Or Uninstall

Update to the latest published PyPI version:

```powershell
uv pip install --upgrade sim-plugin-workbench
```

Update from the latest GitHub `main` branch:

```powershell
uv pip install --upgrade "git+https://github.com/svd-ai-lab/sim-plugin-workbench.git@main"
```

Uninstall:

```powershell
uv pip uninstall sim-plugin-workbench
```

## Troubleshooting

- `sim` command not found: install sim-cli in the same Python environment.
- Driver not discovered: reinstall the plugin and run `sim check workbench`.
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
