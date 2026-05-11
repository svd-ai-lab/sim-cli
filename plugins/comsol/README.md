# sim-plugin-comsol

Use Codex, Claude Code, or another AI agent to work with
[COMSOL Multiphysics](https://www.comsol.com) models from the workflow you
already use.

`sim-plugin-comsol` gives an agent practical COMSOL control paths: inspect
saved `.mph` files, build or modify models through the COMSOL Java API, run
studies, check live-session health, and work through a shared visible COMSOL
Desktop session when the engineer wants to watch or intervene.

COMSOL itself and its `mph` Python binding are not bundled. See
[LICENSE-NOTICE.md](LICENSE-NOTICE.md).

## What an agent can do with COMSOL

- Load and modify existing COMSOL `.mph` models.
- Build and solve a model step by step while you watch the Model Builder.
- Inspect a saved `.mph` file before deciding what to change.
- Run bounded edits, checks, plots, and result-export steps through COMSOL's
  Java API.
- Keep a structured audit trail of commands, health checks, and generated
  artifacts so results can be reviewed rather than guessed.

This repository is intended to be the complete COMSOL agent bundle: driver and
bundled COMSOL skill. A receiving agent should not need a separate COMSOL skill
checkout.

## Choose the right COMSOL workflow

### 1. Agent-owned live Desktop session — best for repeatable work

Use this when the agent should build, inspect, solve, and debug a model across
multiple steps while the engineer watches a live COMSOL Desktop client:

```powershell
uv run sim connect --solver comsol --ui-mode gui --driver-option visual_mode=shared-desktop
uv run sim inspect session.health
uv run sim exec --file step.py
```

`shared-desktop` starts `comsolmphserver`, attaches a full COMSOL Desktop
client to that server, and binds agent snippets to the Desktop active model
tag. `session.health` should report `model_builder_live: true` and a
`live_model_binding.ok` value of `true` before relying on the GUI as a live
view of agent edits.

Prefer this path for reliable multi-step model building, solving, structured
inspection, and repeatable agent workflows.

### 2. Saved `.mph` inspection — best before changing a file

When the user only needs to know what is in a saved COMSOL model, use the
bundled offline inspection helpers before launching a heavyweight COMSOL
session. This is the right first step for questions like: "what physics,
parameters, studies, meshes, and result nodes are in this `.mph`?"

## Install

For agent projects, install sim-cli-core and the COMSOL plugin in the project
environment:

```powershell
uv init  # only if this is not already a uv project
uv add sim-cli-core sim-plugin-comsol
uv run sim plugin sync-skills --target .agents/skills --copy
uv run sim check comsol
uv run sim plugin doctor comsol --deep
```

For Claude Code, sync the bundled skill to `.claude/skills` instead:

```powershell
uv run sim plugin sync-skills --target .claude/skills --copy
```

`uv run sim ...` runs sim from this project environment, so it sees this
project's plugins. Without uv, create and activate a venv, then install
`sim-cli-core` plus this plugin with `python -m pip`.

## Agent quickstart

Give Codex, Claude Code, or another coding agent this instruction when the task
is about COMSOL:

```text
Use the bundled COMSOL skill from sim-plugin-comsol. First identify whether the
user wants: (1) a reliable agent-owned shared Desktop session or (2) offline
inspection of a saved .mph file. For reliable visible co-editing, use
`sim connect --solver comsol --ui-mode gui --driver-option visual_mode=shared-desktop`
and verify `session.health.live_model_binding.ok`. For non-trivial modeling,
establish the target model identity and working folder first: load the given
.mph, or set a descriptive model tag/title and save an early checkpoint .mph
under a case workdir. Build and solve the requested model one bounded step at a
time.
```

The bundled skill entry point is:

```text
src/sim_plugin_comsol/_skills/comsol/SKILL.md
```

## How it relates to sim-cli

`sim-plugin-comsol` is a Python package that extends
[sim-cli](https://github.com/svd-ai-lab/sim-cli). sim-cli provides the common
agent runtime surface (`connect`, `exec`, `inspect`, `screenshot`, `run`), while
this plugin supplies the COMSOL-specific driver and COMSOL agent skill.

The plugin registers three entry-point groups:

```toml
[project.entry-points."sim.drivers"]
comsol = "sim_plugin_comsol:ComsolDriver"

[project.entry-points."sim.skills"]
comsol = "sim_plugin_comsol:skills_dir"

[project.entry-points."sim.plugins"]
comsol = "sim_plugin_comsol:plugin_info"
```

`sim.drivers` exposes the driver class; `sim.skills` exposes a directory of
skill files bundled inside the wheel; `sim.plugins` exposes plugin metadata for
discovery.

## Develop

```bash
git clone https://github.com/svd-ai-lab/sim-plugin-comsol
cd sim-plugin-comsol
uv sync
uv run sim plugin list
uv run sim check comsol
uv run pytest
```

## License

Apache-2.0. See [LICENSE](LICENSE) and [LICENSE-NOTICE.md](LICENSE-NOTICE.md).
