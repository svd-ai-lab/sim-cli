# Installing sim plugins

`sim-cli-core` ships with no solver drivers built in. Each solver integration
lives in a separate `sim-plugin-<solver>` Python package. A plugin normally
provides both:

- a driver entry point that `sim` can load
- a bundled `_skills/<solver>/` directory that an agent can read

Use `uv` or Python packaging tools to install packages. Use `sim` to verify
solver readiness and sync bundled skills into the agent project.

## TL;DR

| Situation | Command |
|---|---|
| Add sim and COMSOL to this uv project | `uv add sim-cli-core sim-plugin-comsol` |
| Run sim from this uv project | `uv run sim check comsol` |
| Sync skills for Codex or GitHub Copilot | `uv run sim plugin sync-skills --target .agents/skills --copy` |
| Sync skills for Claude Code | `uv run sim plugin sync-skills --target .claude/skills --copy` |
| Inspect installed plugins | `uv run sim plugin list` |
| Verify plugin and solver path | `uv run sim plugin doctor comsol --deep` |

## uv project setup

Use this path for agent projects and reproducible engineering work. Run from
the project root:

```bash
uv init  # only if this is not already a uv project
uv add sim-cli-core sim-plugin-comsol
uv run sim plugin sync-skills --target .agents/skills --copy
uv run sim check comsol
uv run sim plugin doctor comsol --deep
```

`uv run sim ...` runs `sim` from the current project environment, so it sees
the plugin packages declared by that project. Bare `sim ...` runs whichever
`sim` is on `PATH`.

For Claude Code, sync to `.claude/skills` instead:

```bash
uv run sim plugin sync-skills --target .claude/skills --copy
```

## Without uv

If you cannot use `uv`, create and activate a normal Python virtual environment,
then install `sim-cli-core` and the solver plugin into that environment.

macOS/Linux:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install sim-cli-core sim-plugin-comsol
sim plugin sync-skills --target .agents/skills --copy
sim check comsol
sim plugin doctor comsol --deep
```

Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install sim-cli-core sim-plugin-comsol
sim plugin sync-skills --target .agents/skills --copy
sim check comsol
sim plugin doctor comsol --deep
```

In an activated environment, bare `sim ...` is fine because the environment is
explicit.

## What uv installs and what sim does

Python packages live in the environment that runs `sim`. Solver plugins are
independent Python distributions, but current plugin discovery uses Python
entry points from the environment running `sim`.

`uv` or `pip` handles package installation:

```bash
uv add sim-cli-core sim-plugin-comsol
uv add "git+https://github.com/svd-ai-lab/sim-plugin-matlab@main"
uv add ./sim-plugin-comsol
uv add ./sim_plugin_comsol-<version>-py3-none-any.whl
```

`sim` handles solver-specific checks and agent skill materialization:

```bash
uv run sim plugin list
uv run sim plugin info comsol
uv run sim plugin doctor comsol --deep
uv run sim plugin sync-skills --target .agents/skills --copy
uv run sim check comsol
```

Skills are different from Python packages. The plugin package lives in Python's
site-packages; the bundled skill is synced into an agent-readable directory such
as `.agents/skills` or `.claude/skills`.

## sim plugin install

`sim plugin install <source>` is still available for direct wheel, Git, local
checkout, or non-uv workflows. It installs into the Python interpreter running
`sim` unless you pass `--python`.

Examples:

```bash
sim plugin install sim-plugin-comsol
sim plugin install sim-plugin-comsol==<version>
sim plugin install https://example.com/sim_plugin_comsol-<version>-py3-none-any.whl
sim plugin install ./sim_plugin_comsol-<version>-py3-none-any.whl
sim plugin install ./sim-plugin-comsol
sim plugin install -e ./sim-plugin-comsol
sim plugin install git+https://github.com/svd-ai-lab/sim-plugin-comsol
```

Only use `--python` when you intend to run `sim` from that same Python
environment or otherwise know that the plugin will be discoverable there:

```bash
sim plugin install sim-plugin-comsol --python /path/to/venv/bin/python
```

## Skill sync targets

Use the two common agent targets directly:

- `.agents/skills` for Codex and GitHub Copilot projects
- `.claude/skills` for Claude Code projects

If you omit `--target`, the CLI uses Claude-oriented defaults:

- if `./.claude/` exists, sync to `./.claude/skills/`
- otherwise sync to `~/.claude/skills/`

Use `--copy` when symlinks are inconvenient or unsupported. Re-running
`sync-skills` is idempotent.

## Project manifests with sim.toml

For reproducible Python packages, commit `pyproject.toml` and `uv.lock`. Use
`sim.toml` for solver defaults, workspace settings, and optional plugin source
declarations.

Create a starter file:

```bash
uv run sim init
```

Example `sim.toml`:

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
uv run sim plugin sync-skills --target .agents/skills --copy
uv run sim check comsol
```

`sim setup` remains useful when a project chooses to declare plugin sources in
`sim.toml`; the uv project dependency list remains the clearest place to pin
the Python environment.

## Discovery

A curated plugin list lives in the [sim-plugin-index](https://github.com/svd-ai-lab/sim-plugin-index) README — a markdown table with the install string for each plugin. Agents and humans read it directly.

## Verifying an install

After installation, check the plugin and solver path:

```bash
uv run sim plugin list
uv run sim plugin info comsol
uv run sim plugin doctor comsol
uv run sim plugin doctor comsol --deep
uv run sim check comsol
```

`plugin doctor` checks entry points, driver instantiation, bundled skills, and
the plugin compatibility metadata. `--deep` also calls solver detection, so it
can fail when the plugin is valid but the simulation solver is missing, not
available to the current process, or installed in an unsupported location.
