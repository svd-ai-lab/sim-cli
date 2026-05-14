<div align="center">

<img src="assets/banner.svg" alt="sim — agent runtime for physics simulations" width="820">

<br>

**sim-cli lets AI agents operate CAE solvers one verified step at a time.**

`sim` is an open-source CLI and local runtime that lets Codex, Claude Code,
GitHub Copilot, Gemini, and other agents work with simulation software through
solver-specific plugins and bundled skills. An agent can check what is
installed, connect to a solver, inspect live state, execute bounded modeling
or analysis steps, verify result/state, and save checkpoints/artifacts for
engineering review.

<p align="center">
  <a href="#quick-start-agent-setup"><img src="https://img.shields.io/badge/Quick_Start-agent_setup-3b82f6?style=for-the-badge" alt="Quick Start"></a>
  <a href="#solver-plugins"><img src="https://img.shields.io/badge/Solvers-plugin_based-22c55e?style=for-the-badge" alt="Solver plugins"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-eab308?style=for-the-badge" alt="License"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/CLI-Click_8-blue" alt="Click">
  <img src="https://img.shields.io/badge/server-FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/transport-HTTP%2FJSON-orange" alt="HTTP/JSON">
  <img src="https://img.shields.io/badge/status-alpha-f97316" alt="Status: alpha">
</p>

[Quick Start](#quick-start-agent-setup) · [COMSOL + Codex](#example-comsol-and-codex-on-one-machine) · [Agent Loop](#the-agent-loop) · [Remote Solvers](#local-vs-remote-solvers) · [Plugins](#solver-plugins) · [Commands](#common-commands)

</div>

---

## Who this is for

`sim` is for agents and people trying to get real simulation work done.

- **CAE engineers who already script solvers** and want an agent to help
  automate COMSOL, Abaqus, HFSS, Fluent, MATLAB, LTspice, and similar tools
  without losing inspection and recovery between steps.
- **Design engineers and occasional simulation users** who have agent
  experience and want an agent-assisted workflow: ask for a simulation, watch
  the model evolve, review screenshots or plots, and keep final artifacts.
- **AI agents** reading this repository to learn the safe setup and operating
  loop before touching a solver.
- **Engineering leaders** evaluating whether agent-assisted simulation can be
  repeatable, reviewable, and compatible with existing solver installations.

Plugin authoring, runtime internals, and driver protocol details live in
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## What sim gives an agent

LLMs can often write solver scripts, but a one-shot script is a weak workflow:
it hides intermediate state, fails late, and makes recovery difficult.

`sim` gives an agent a small, repeatable control surface — detect the
environment, attach to a live session, inspect state, run one bounded step,
verify, and checkpoint. See [The agent loop](#the-agent-loop) for the full
sequence.

A bounded CAE step is one small modeling, meshing, solving, or postprocessing
action that can be inspected and verified before continuing. Examples: create a
geometry feature, assign a material, apply a boundary condition, generate a
mesh, run one study, extract a probe value, create a plot, or export a result
table.

The solver-specific knowledge is not baked into the core CLI. It comes from
plugins. A plugin can provide both:

- a **driver**, so `sim` can launch or talk to the solver
- a **skill**, so the agent knows the solver-specific workflow, pitfalls, and
  inspection rules

## Human-in-the-loop collaboration

`sim` is designed for shared control, not unattended black-box automation.
When a solver plugin exposes live state through `sim inspect`, the agent can
re-read the current solver session after each meaningful step. That means an
engineer can cut in through the solver GUI, change geometry, parameters,
boundary conditions, plots, or saved artifacts, then ask the agent to inspect
again and continue from the real current state.

This is the collaboration model: the human can watch, correct, and steer; the
agent keeps using inspection and checkpoints instead of assuming its previous
script still matches the real solver state.

## Quick Start: agent setup

Use this path when the agent and solver are on the same machine. You do not
need to start `sim serve` manually for the local happy path; `sim connect`
will use the local runtime. The default docs use
[`uv`](https://docs.astral.sh/uv/) so agents run the `sim` and plugins declared
by the current project instead of guessing which executable is on `PATH`.

`uv run sim ...` runs `sim` from this project environment, so it sees this
project's installed solver plugins. Run from the project root:

```bash
uv init  # only if this is not already a uv project
uv add sim-cli-core sim-plugin-comsol
uv run sim plugin sync-skills --target .agents/skills --copy
uv run sim check comsol
uv run sim plugin doctor comsol --deep
```

The `sync-skills` target depends on your agent: use `.agents/skills` for Codex
and GitHub Copilot, or `.claude/skills` for Claude Code. Substitute that path in
any `sync-skills` command shown below.

### Without uv

If you cannot use `uv`, create a normal Python virtual environment, install
`sim-cli-core` and the solver plugin into that environment, then run `sim`
from the activated environment:

```bash
python -m venv .venv
source .venv/bin/activate   # Windows PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install sim-cli-core sim-plugin-comsol
sim plugin sync-skills --target .agents/skills --copy
sim check comsol
sim plugin doctor comsol --deep
```

## Hand the task to your agent

After setup, give your agent the **engineering goal in plain language** — the
simulation you want and the quantity you want reported. You do not need to
recite the operating loop: the bundled solver skill already enforces the
inspect / verify / checkpoint discipline once the agent loads it.

Two things are still worth telling the agent explicitly:

- Run `sim` through this project with `uv run sim ...` so it sees the project's
  installed plugins.
- Don't guess solver API names — inspect the live model or the solver's local
  docs first. If you change something manually in the solver GUI, ask the agent
  to re-inspect live state before continuing.

A concrete example follows below.

## Example: COMSOL and Codex on one machine

Follow [Quick Start](#quick-start-agent-setup) to install `sim-cli-core` and
`sim-plugin-comsol` and sync the skill — those commands already use COMSOL.
Then ask Codex for the actual task:

```text
Simulate the natural-convection cooling of attached `pcb.mph` and report the
maximum junction temperature. Use the installed COMSOL skill. Check COMSOL with
`uv run sim check comsol` first. If you need a visible live COMSOL Desktop
session, connect with `--ui-mode gui`.
```

The prompt names a goal and a quantity to report — not a list of `sim`
sub-steps. The COMSOL skill supplies the rest: session health and model
identity checks, checkpoint policy, and step-by-step build/solve discipline.

For COMSOL-specific details such as shared Desktop mode, offline `.mph`
inspection, Desktop attach fallback, model identity checks, and checkpoint
policy, follow the bundled COMSOL skill.

## Why CLI-first?

Engineering simulation is file-based, scriptable, local, artifact-heavy, and
long-running. CAE agents work with solver executables, model files,
Python/Java/journal scripts, shell commands, logs, checkpoints, and plots — a
CLI command surface composes with all of that and matches how Codex CLI, Claude
Code, and other coding agents already operate.

MCP is useful for API-style integrations and remote tool discovery, but a broad
MCP surface adds context overhead and wrapper maintenance. For COMSOL, Abaqus,
Ansys Workbench, OpenFOAM, LTspice, and similar solvers, sim-cli keeps the
source of truth as a small, auditable command loop.

## The agent loop

For any solver, the agent should prefer this loop over one large generated
script:

1. `uv run sim check <solver>` to detect installed solver versions and plugin
   compatibility.
2. `uv run sim connect --solver <solver> ...` for live stateful work, or
   `uv run sim run` for a deterministic one-shot script.
3. `uv run sim inspect session.versions` and the solver-specific health or
   identity target before changing state.
4. `uv run sim exec --file step.py --label <step>` for one bounded modeling
   or analysis step.
5. `uv run sim inspect last.result` and solver-specific state.
6. Verify the result/state using solver-specific numerical evidence when available.
7. Save checkpoints and artifacts when the solver plugin or skill requires
   them.
8. `uv run sim disconnect` when the session is done.

Screenshots and plots help humans review the result, but engineering
acceptance should prefer numeric evidence when the solver skill defines it:
mesh statistics, convergence, finite probes, conservation checks, tolerances,
or expected trends.

## Local vs remote solvers

**Same machine:** install `sim-cli-core` and the solver plugin into the project
environment, sync the skill to your agent, then use `uv run sim connect`. Do
not add `--host` unless you are intentionally talking to a remote `sim serve`.

**Remote solver workstation, lab box, or HPC login node:** install
`sim-cli-core` and the solver plugin on the solver host, start `sim serve`
there, then point the local agent at that host:

```bash
# On the solver host.
uv run sim serve --host 0.0.0.0 --port 7600

# On the agent/control machine.
uv run sim --host <solver-host-ip> check <solver>
uv run sim --host <solver-host-ip> connect --solver <solver>
uv run sim --host <solver-host-ip> inspect session.summary
uv run sim --host <solver-host-ip> disconnect
```

Only bind `sim serve` to a trusted network such as a VPN, Tailscale, or a
protected LAN. The runtime currently has no auth layer, and `/connect` plus
`/exec` can execute solver-side code.

## Solver plugins

`sim-cli-core` ships with no solver drivers built in. Each simulation solver is
reached through an explicit plugin package.

A few representative plugins:

| Solver | Package spec | Plugin repo |
| --- | --- | --- |
| COMSOL | `sim-plugin-comsol` | [sim-plugin-comsol](https://github.com/svd-ai-lab/sim-plugin-comsol) |
| Abaqus | `sim-plugin-abaqus` | [sim-plugin-abaqus](https://github.com/svd-ai-lab/sim-plugin-abaqus) |
| Ansys Workbench | `sim-plugin-workbench` | [sim-plugin-workbench](https://github.com/svd-ai-lab/sim-plugin-workbench) |
| Autodesk Fusion 360 | _in development_ | [sim-plugin-fusion360](https://github.com/svd-ai-lab/sim-plugin-fusion360) |
| LTspice | `sim-plugin-ltspice` | [sim-plugin-ltspice](https://github.com/svd-ai-lab/sim-plugin-ltspice) |

For the curated full list, see [sim-plugin-index](https://github.com/svd-ai-lab/sim-plugin-index).

After adding any plugin package, sync its bundled skill and verify that the local
solver can be reached:

```bash
uv run sim plugin list
uv run sim plugin sync-skills --target .agents/skills --copy  # or .claude/skills for Claude Code
uv run sim check <solver>
uv run sim plugin doctor <solver> --deep
```

For direct wheel, Git, local checkout, or non-uv package workflows, see
[docs/plugin-install.md](docs/plugin-install.md).

## Project setup with sim.toml

For reproducible Python packages, commit the `pyproject.toml` and `uv.lock`
created by `uv add`. Use `sim.toml` for solver defaults and workspace settings:

```bash
uv run sim init
```

Example:

```toml
[sim]
default_solver = "comsol"
workspace = "./workspace"

[[sim.plugins]]
name = "comsol"
package = "sim-plugin-comsol"
```

Then a fresh checkout can run:

```bash
uv sync
uv run sim setup --dry-run
uv run sim plugin sync-skills --target .agents/skills --copy  # or .claude/skills for Claude Code
```

## Common commands

| Command | Use it for |
|---|---|
| `uv run sim plugin list` | Show plugins visible in this project environment. |
| `uv run sim plugin info <solver>` | Show plugin metadata and compatibility summary. |
| `uv run sim plugin doctor <solver> --deep` | Check plugin wiring plus local solver detection. |
| `uv run sim plugin sync-skills --target .agents/skills --copy` | Materialize installed plugin skills for your agent (`.claude/skills` for Claude Code). |
| `uv run sim check <solver>` | Detect local or remote solver installs. |
| `uv run sim connect --solver <solver>` | Open a persistent solver session. |
| `uv run sim exec --file step.py` | Run one bounded step in the live session. |
| `uv run sim inspect <target>` | Query session, result, or solver-specific state. |
| `uv run sim run script.py --solver <solver>` | Run a deterministic one-shot script. |
| `uv run sim disconnect` | Tear down the active session. |
| `uv run sim setup` | Validate `sim.toml` and report declared plugin package specs. |

Run `uv run sim describe` for a machine-readable command manifest, or
`uv run sim <command> --help` for exact options.

## Solver ownership

`sim-cli` does not bundle or redistribute simulation solvers or vendor SDKs.
Install and operate each underlying solver according to its vendor terms. See
[NOTICE](NOTICE) for optional SDK dependency notes.

`sim-cli` is an independent open-source project and is not affiliated with,
endorsed by, or sponsored by any solver vendor. Product, solver, and company
names remain the property of their respective owners.

## Developer docs

- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) - project setup, layout, driver
  development, and architecture notes
- [docs/plugin-install.md](docs/plugin-install.md) - plugin installation
  reference

## License

Apache-2.0 - see [LICENSE](LICENSE).
