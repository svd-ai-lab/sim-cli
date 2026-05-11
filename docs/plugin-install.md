# Installing sim plugins

`sim-cli-core` ships with no solver drivers built in. Each solver integration
lives in a separate `sim-plugin-<solver>` package. A plugin normally provides
both:

- a driver entry point that `sim` can load
- a bundled `_skills/<solver>/` directory that an agent can read

Use this reference to install plugins and expose their bundled skills to Codex,
GitHub Copilot, Claude Code, or another agent.

## TL;DR

| Situation | Command |
|---|---|
| Discover available plugins | `sim plugin catalog` |
| Install a PyPI plugin | `sim plugin install sim-plugin-comsol` |
| Install a pinned PyPI plugin | `sim plugin install sim-plugin-comsol==<version>` |
| Install from a private package index | `sim plugin install sim-plugin-mechanical --extra-index-url https://example.com/simple/` |
| Install from a direct artifact URL | `sim plugin install https://example.com/sim_plugin_comsol-<version>-py3-none-any.whl` |
| Install from a local wheel | `sim plugin install ./sim_plugin_comsol-<version>-py3-none-any.whl` |
| Install from a local plugin checkout | `sim plugin install ./sim-plugin-comsol` |
| Editable install for plugin authors | `sim plugin install -e ./sim-plugin-comsol` |
| Sync installed skills for Codex or GitHub Copilot | `sim plugin sync-skills --target .agents/skills --copy` |
| Sync installed skills for Claude Code | `sim plugin sync-skills --target .claude/skills --copy` |

## Python environment and plugin visibility

With the recommended user install:

```bash
uv tool install sim-cli-core
```

`uv` creates a dedicated tool environment for `sim-cli-core`. The executable is
placed in `$(uv tool dir --bin)`, usually `~/.local/bin/sim`. The tool
environment is under `$(uv tool dir)/sim-cli-core`, usually
`~/.local/share/uv/tools/sim-cli-core`.

By default, `sim plugin install <source>` installs the plugin package into the
Python interpreter that is running `sim`. For the recommended uv tool setup,
that means plugins are installed into the same `sim-cli-core` tool environment,
not into your current project `.venv`.

This is a visibility rule, not a packaging coupling. Solver plugins are
independent Python distributions, but the current CLI discovers them through
Python entry points from the environment running `sim`.

For a project-scoped uv environment, install both `sim-cli-core` and the solver
plugins into that project and run `sim` through `uv run`:

```bash
uv add sim-cli-core sim-plugin-comsol
uv run sim check comsol
uv run sim plugin sync-skills --target .agents/skills --copy
```

You can override the install target:

```bash
sim plugin install sim-plugin-comsol --python /path/to/venv/bin/python
```

Only use `--python` when you intend to run `sim` from that same Python
environment or otherwise know that the plugin will be discoverable there.

Skills are different from Python packages. The plugin package lives in Python's
site-packages; the bundled skill is synced into an agent-readable directory such
as `.agents/skills` or `.claude/skills`.

## Install sources

`sim plugin install <source>` passes explicit install sources to pip or
`uv pip`. It does not silently resolve short catalogue names.

Supported sources:

1. `sim-plugin-<name>` or `sim-plugin-<name>==<version>` - exact package
   specs.
2. `sim-plugin-<name> --extra-index-url https://.../simple/` - package spec
   plus a private Python package index.
3. `https://...whl` or `https://...tar.gz` - direct wheel or sdist URL.
4. `./path/to/dir` - local plugin source directory.
5. `./path/to/wheel.whl` or `./path/to/sdist.tar.gz` - local artifact.
6. `git+https://...` or `git+ssh://...` - Git source, when Git is available.

Bare solver names such as `comsol` or `ltspice` are catalogue IDs, not install
sources. Run `sim plugin catalog` to see available plugins and their
copy-paste install strings.

## Skill sync targets

After a successful install, `sim plugin install` runs skill sync unless you
pass `--no-sync`.

Use the two common agent targets directly:

- `.agents/skills` for Codex and GitHub Copilot projects
- `.claude/skills` for Claude Code projects

Default behavior is Claude-oriented:

- if `./.claude/` exists, sync to `./.claude/skills/`
- otherwise sync to `~/.claude/skills/`

For Codex or GitHub Copilot, explicitly sync into the project skill directory:

```bash
sim plugin install sim-plugin-comsol
sim plugin sync-skills --target .agents/skills --copy
```

For project-local Claude Code skills, use:

```bash
sim plugin sync-skills --target .claude/skills --copy
```

Use `--copy` when symlinks are inconvenient or unsupported. Re-running
`sync-skills` is idempotent.

## Discovery catalogue

Agents can inspect available plugins before installing anything:

```bash
sim plugin catalog
sim --json plugin catalog
```

The catalogue is advisory metadata. It helps users and agents find official
install strings, but the install command still requires an explicit package,
URL, Git source, or local path.

## Online installs

For a normal online install:

```bash
uv tool install sim-cli-core
sim plugin install sim-plugin-comsol
sim check comsol
sim plugin doctor comsol --deep
```

Requirements:

- `sim-cli-core` installed and on `PATH`
- `uv` available, or Python with `pip` available to the interpreter running
  `sim`
- network access to the package index, direct URL, or Git host you provide
- the underlying simulation solver installed if `--deep` detection should
  succeed

In the common uv tool setup, do not pass `--python`; let the plugin install into
the same tool environment as `sim`. If you intentionally maintain another
Python environment that should own both `sim` and its plugins, pin that
interpreter:

```bash
sim plugin install sim-plugin-comsol --python /path/to/venv/bin/python
```

Then run `sim` from that same environment so plugin entry points are visible.

## Offline installs

If a colleague or release page provides a wheel or sdist:

```bash
sim plugin install ./sim_plugin_comsol-<version>-py3-none-any.whl

# Codex or GitHub Copilot
sim plugin sync-skills --target .agents/skills --copy

# Claude Code
sim plugin sync-skills --target .claude/skills --copy
```

The skill ships inside the wheel, so the same artifact can provide both the
driver and the agent instructions. No network access is required beyond the
artifact you already have.

## Private plugins

Private plugin availability depends on the solver, team, and distribution
model. Private wrappers should be distributed through explicit private repos,
direct wheel URLs, or standard private Python package indexes:

```bash
sim plugin install sim-plugin-mechanical --extra-index-url https://example.com/simple/
sim plugin install git+ssh://git@example.com/acme/sim-plugin-internal
sim plugin install https://example.com/wheels/sim_plugin_internal-0.1.0-py3-none-any.whl
```

Contact <contact@svd-ai-lab.com> to discuss private plugin access.

## Project manifests with sim.toml

For a project that an agent should be able to bootstrap reproducibly, commit a
`sim.toml` manifest.

Create a starter file:

```bash
sim init
```

Example `sim.toml`:

```toml
[sim]
default_solver = "comsol"
workspace = "./workspace"

[[sim.plugins]]
name = "comsol"
package = "sim-plugin-comsol"

[[sim.plugins]]
name = "ltspice"
package = "sim-plugin-ltspice"
version = "==0.2.3"

[[sim.plugins]]
name = "internal"
git = "ssh://git@example.com/acme/sim-plugin-internal"

[[sim.plugins]]
name = "offline"
wheel = "./vendor/sim_plugin_offline-0.1.0-py3-none-any.whl"
```

Then run:

```bash
sim setup --dry-run
sim setup
```

`sim setup` reads `[[sim.plugins]]`, derives each explicit install source, and
installs those plugins. It is idempotent for a fresh checkout workflow. After
setup, sync skills to the agent target you use:

```bash
# Codex or GitHub Copilot
sim plugin sync-skills --target .agents/skills --copy

# Claude Code
sim plugin sync-skills --target .claude/skills --copy
```

## Verifying an install

After installation, check the plugin and solver path:

```bash
sim plugin list
sim plugin info comsol
sim plugin doctor comsol
sim plugin doctor comsol --deep
sim check comsol
```

`plugin doctor` checks entry points, driver instantiation, bundled skills, and
the plugin compatibility metadata. `--deep` also calls solver detection, so it
can fail when the plugin is valid but the simulation solver is missing, not
available to the current process, or installed in an unsupported location.

## Editable installs

Plugin authors can install from a local checkout:

```bash
sim plugin install -e ./sim-plugin-comsol
```

That is equivalent to editable pip installation plus best-effort skill sync.
Code edits take effect on the next Python process.
