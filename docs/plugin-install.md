# Installing sim plugins

`sim` ships with no solver drivers built-in (since v1.0). Each driver +
its skill lives in a separate `sim-plugin-<solver>` package. This doc
covers every way to install one.

## TL;DR

| Situation | Command |
|---|---|
| Online, named plugin | `sim plugin install coolprop` |
| Online, plugin you cloned locally | `sim plugin install ./sim-plugin-coolprop` |
| Offline (you have a wheel file) | `sim plugin install ./sim_plugin_coolprop-0.1.0-py3-none-any.whl` |
| Air-gapped (you have a bundle dir) | `sim plugin install --offline --from-dir ./bundle/ --all` |
| Editable (you author plugins) | `sim plugin install -e ./sim-plugin-coolprop` |
| Commercial plugin (private) | `sim plugin install fluent --include-commercial` <!-- allow-vendor-name: user-facing install example for licensed users --> |

## How `sim plugin install <source>` resolves

`<source>` accepts any of:

1. `<name>` — looks up the plugin in the curated index. Tries the
   `latest_wheel_url` first (HTTPS, no git or `gh` needed); falls back to
   `git+https://...` if the wheel URL is unreachable.
2. `<name>@<version>` — pinned version from the index.
3. `https://...whl` or `https://...tar.gz` — direct URL to a wheel or
   sdist. Plain pip + HTTPS, works behind corporate proxies.
4. `./path/to/dir` — local plugin source directory. `pip install <dir>`.
5. `./path/to/wheel.whl` or `./path/to/sdist.tar.gz` — local artifact.
   `pip install <path>`.
6. `git+https://...` or `git+ssh://...` — git URL (when git is available).

After the package installs, `sim plugin install` runs `sync-skills`
automatically so the plugin's bundled `_skills/<solver>/` becomes
discoverable to Claude Code (or any consumer of `.claude/skills/`).

## Online (HTTPS-only)

```sh
sim plugin install coolprop
```

This is enough on a typical developer laptop. Requires:

- `sim-cli-core` already installed.
- HTTPS access to GitHub Releases (for wheel) or GitHub repo (for git fallback).
- `pip` (it ships with Python).

Does NOT require:

- `git` CLI.
- `gh` CLI.
- A GitHub account or auth (for OSS plugins).

## Offline (single artifact)

If you have a wheel or sdist file (downloaded from a release page, sent by
a colleague, copied off a USB stick):

```sh
sim plugin install ./sim_plugin_coolprop-0.1.0-py3-none-any.whl
```

The skill ships *inside* the wheel under `_skills/<solver>/`, so this
single command brings up both the driver and the skill. No network access
is required.

## Air-gapped (bundle)

For lab/regulated environments without external network, the bundle flow:

**On a connected machine:**

```sh
sim plugin bundle coolprop simpy gmsh --output ./plugins-bundle/
```

This produces:

```
plugins-bundle/
  index.json                                         (filtered to bundled plugins,
                                                       with file:// URLs)
  sim_plugin_coolprop-0.1.0-py3-none-any.whl
  sim_plugin_simpy-0.1.0-py3-none-any.whl
  sim_plugin_gmsh-0.1.0-py3-none-any.whl
```

**Ship the directory** (USB, secure file transfer, etc.).

**On the air-gapped machine:**

```sh
sim plugin install --offline --from-dir ./plugins-bundle/ coolprop simpy gmsh
# or, install everything in the bundle:
sim plugin install --offline --from-dir ./plugins-bundle/ --all
```

`--offline` forces the resolver to use the bundle's local `index.json` and
refuse network calls.

## Editable (plugin authors)

If you're authoring or debugging a plugin:

```sh
sim plugin install -e ./sim-plugin-coolprop
```

Equivalent to `pip install -e ./sim-plugin-coolprop`, plus syncing skills.
Code edits take effect on next process; you never need to reinstall during
development.

## Commercial plugins (private repos)

Commercial plugins live in private repos because their existence in a
public listing would reveal that maintainers have access to that paid
tool. They are not in the public index.

For licensed users:

```sh
gh auth login                                  # one-time
sim plugin install fluent --include-commercial   # <!-- allow-vendor-name: example, plugin name is the user-facing identifier -->
```

`--include-commercial` consults a private commercial index. Without GitHub
auth, the command fails clean (no leak).

Direct install also works:

```sh
sim plugin install git+ssh://git@github.com/svd-ai-lab/sim-plugin-<x>.git
```

Or, if a teammate sent you the wheel out-of-band:

```sh
sim plugin install ./sim_plugin_<x>-1.0.0-py3-none-any.whl
```

## Surviving `uv sync`

`uv sync` rebuilds the project venv from declared dependencies and wipes
anything else. To keep installed plugins across `uv sync` invocations,
`sim plugin install` writes the install record to a managed
`[tool.sim.plugins]` table in your project's `pyproject.toml` (or to
`~/.sim/plugins.toml` for `--global`):

```toml
[tool.sim.plugins]
coolprop = { name = "coolprop", source = "index", version = ">=0.1.0" }
gmsh     = { git = "https://github.com/svd-ai-lab/sim-plugin-gmsh", rev = "v0.1.0" }
fluent   = { wheel = "./vendor/sim_plugin_fluent-1.2.0-py3-none-any.whl" }   # <!-- allow-vendor-name: example showing how a commercial plugin is recorded in pyproject -->
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
sim plugin doctor --all --json   # machine-readable
```

`doctor` checks that the plugin's entry-points resolve, the driver
instantiates, the skill directory exists, and the
`compatibility.yaml`-declared `sim_cli_core` constraint is satisfied.
