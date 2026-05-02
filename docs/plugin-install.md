# Installing sim plugins

`sim` ships with no solver drivers built-in (since v1.0). Each driver +
its skill lives in a separate `sim-plugin-<solver>` package. This doc
covers every way to install one.

## TL;DR

| Situation | Command |
|---|---|
| Discover available plugins | `sim plugin catalog` |
| PyPI package | `sim plugin install sim-plugin-coolprop` |
| Pinned PyPI package | `sim plugin install sim-plugin-coolprop==0.1.0` |
| Private package index | `sim plugin install sim-plugin-mechanical --extra-index-url https://example.com/simple/` |
| Direct URL | `sim plugin install https://example.com/sim_plugin_coolprop-0.1.0-py3-none-any.whl` |
| Online, plugin you cloned locally | `sim plugin install ./sim-plugin-coolprop` |
| Offline (you have a wheel file) | `sim plugin install ./sim_plugin_coolprop-0.1.0-py3-none-any.whl` |
| Editable (you author plugins) | `sim plugin install -e ./sim-plugin-coolprop` |

## How `sim plugin install <source>` resolves

`<source>` accepts any of:

1. `sim-plugin-<name>` or `sim-plugin-<name>==<version>` — exact package
   spec passed directly to pip/uv.
2. `sim-plugin-<name> --extra-index-url https://.../simple/` — exact
   package spec plus an additional private Python package index.
3. `https://...whl` or `https://...tar.gz` — direct URL to a wheel or
   sdist. Plain pip + HTTPS, works behind corporate proxies.
4. `./path/to/dir` — local plugin source directory. `pip install <dir>`.
5. `./path/to/wheel.whl` or `./path/to/sdist.tar.gz` — local artifact.
   `pip install <path>`.
6. `git+https://...` or `git+ssh://...` — git URL (when git is available).

Bare short names such as `coolprop` or `ltspice` are catalogue names, not
install sources. Run `sim plugin catalog` to see the official plugin list
with the recommended explicit install command for each, then pass that
command's argument to `sim plugin install`.

After the package installs, `sim plugin install` runs `sync-skills`
automatically so the plugin's bundled `_skills/<solver>/` becomes
discoverable to Claude Code (or any consumer of `.claude/skills/`).

## Discovery catalogue

Agents can discover available plugins without installing anything:

```sh
sim plugin catalog
sim --json plugin catalog
```

The catalogue is for discovery only. Each entry includes a copy-paste
`install` string that callers pass to `sim plugin install`. The catalogue
is advisory metadata; `sim plugin install <short-name>` does not silently
resolve a catalogue name into a URL or package.

## Online

```sh
sim plugin install sim-plugin-coolprop
```

This is enough on a typical developer laptop. Requires:

- `sim-cli-core` already installed.
- HTTPS access to the package index, direct URL, or git host you provide.
- `pip` (it ships with Python).

## Offline (single artifact)

If you have a wheel or sdist file (downloaded from a release page, sent by
a colleague, copied off a USB stick):

```sh
sim plugin install ./sim_plugin_coolprop-0.1.0-py3-none-any.whl
```

The skill ships *inside* the wheel under `_skills/<solver>/`, so this
single command brings up both the driver and the skill. No network access
is required.

## Editable (plugin authors)

If you're authoring or debugging a plugin:

```sh
sim plugin install -e ./sim-plugin-coolprop
```

Equivalent to `pip install -e ./sim-plugin-coolprop`, plus syncing skills.
Code edits take effect on next process; you never need to reinstall during
development.

## Commercial plugins

Commercial plugin availability depends on third-party license conditions.
Private wrappers should be distributed through explicit private repos, direct
wheel URLs, or a standard private Python package index:

```sh
sim plugin install sim-plugin-mechanical --extra-index-url https://example.com/simple/
```

Contact <contact@svd-ai-lab.com> to discuss commercial plugin access.

## Surviving `uv sync`

`uv sync` rebuilds the project venv from declared dependencies and wipes
anything else. To keep installed plugins across `uv sync` invocations,
`sim plugin install` writes the install record to a managed
`[tool.sim.plugins]` table in your project's `pyproject.toml` (or to
`~/.sim/plugins.toml` for `--global`):

```toml
[tool.sim.plugins]
coolprop = { package = "sim-plugin-coolprop", version = ">=0.1.0" }
gmsh     = { git = "https://github.com/svd-ai-lab/sim-plugin-gmsh", rev = "v0.1.0" }
local_plugin = { wheel = "./vendor/sim_plugin_local-1.2.0-py3-none-any.whl" }
```

`sim setup` (or `uv sync && sim plugin install --reapply`) restores them
on a fresh checkout.

For one-shot installs that you don't want recorded:

```sh
sim plugin install <source> --no-record
```

## Verifying

After install, check the plugin loaded cleanly:

```sh
sim plugin list                  # one row per installed plugin
sim plugin doctor coolprop       # detailed validation
sim --json plugin doctor --all   # machine-readable
```

`doctor` checks that the plugin's entry-points resolve, the driver
instantiates, the skill directory exists, and the
`compatibility.yaml`-declared `sim_cli_core` constraint is satisfied.
