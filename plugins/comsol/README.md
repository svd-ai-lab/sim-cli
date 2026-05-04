# sim-plugin-comsol

[COMSOL Multiphysics](https://www.comsol.com) driver and Desktop attach
workflow for [sim-cli](https://github.com/svd-ai-lab/sim-cli), distributed as
an out-of-tree plugin via Python `entry_points`.

The COMSOL solver and its `mph` Python binding are not bundled — you supply them yourself. See [LICENSE-NOTICE.md](LICENSE-NOTICE.md).

## Install

```bash
pip install sim-plugin-comsol
```

After install, agents can drive an already-open COMSOL Desktop through the
server-backed driver. Use this path first when the user wants to watch the
same live model that the agent is building, inspecting, or solving:

```powershell
sim connect --solver comsol --ui-mode gui --driver-option visual_mode=shared-desktop
sim inspect session.health
sim exec --file step.py
```

`shared-desktop` starts `comsolmphserver`, attaches a full COMSOL Desktop
client to that server, and binds agent snippets to the Desktop active model
tag. `session.health` should report `model_builder_live: true` and a
`live_model_binding.ok` value of `true` before relying on the GUI as a live
view of agent edits.

The standalone Java Shell attach helper remains available as a fallback for
ordinary COMSOL Desktop windows that are already open, when switching to an
`mphclient` session is undesirable, or when the task is a small
human-in-the-loop edit:

```powershell
sim-comsol-attach open --json --timeout 120
sim-comsol-attach health --json
sim-comsol-attach exec --file step.java --json
```

Use this fallback for bounded visible edits and quick checks. Prefer
`shared-desktop` for reliable multi-step model building, solving, structured
inspection, and repeatable agent workflows.

sim-cli also auto-discovers the server-backed driver:

```bash
sim drivers | grep comsol
sim run --solver comsol path/to/script.py
```

You can also install through sim-cli's plugin command:

```bash
sim plugin install sim-plugin-comsol
```

## Agent quickstart

This repository is intended to be the complete COMSOL agent bundle. A
receiving agent should not need a separate skill checkout for COMSOL work; the
driver, Desktop attach helper, and COMSOL skill are bundled here.
The only runtime dependency from the sim stack is the installed sim CLI/core
package pulled in by this plugin.

For source-tree development:

```bash
git clone https://github.com/svd-ai-lab/sim-plugin-comsol
cd sim-plugin-comsol
uv sync
uv run sim drivers
uv run sim check comsol
```

The bundled skill entry point is:

```text
src/sim_plugin_comsol/_skills/comsol/SKILL.md
```

Use it as the first agent instruction for COMSOL tasks, for example:

```text
Use the bundled COMSOL skill in this repository. If the user wants reliable
visible co-editing, use the sim runtime with visual_mode=shared-desktop first
and verify session.health live_model_binding.ok. Use Java Shell Desktop attach
only for already-open ordinary Desktop sessions, small edits, or
human-in-the-loop fallback work. Build and solve the requested model one
bounded step at a time.
```

## How it works

The plugin registers the Desktop attach CLI plus three entry-point groups:

```toml
[project.entry-points."sim.drivers"]
comsol = "sim_plugin_comsol:ComsolDriver"

[project.entry-points."sim.skills"]
comsol = "sim_plugin_comsol:skills_dir"

[project.entry-points."sim.plugins"]
comsol = "sim_plugin_comsol:plugin_info"

[project.scripts]
sim-comsol-attach = "sim_plugin_comsol.desktop_attach.cli:main"
```

`sim.drivers` exposes the driver class; `sim.skills` exposes a directory
of skill files bundled inside the wheel; `sim.plugins` exposes plugin
metadata for discovery. `sim-comsol-attach` exposes the Desktop-first
collaboration path.

## Develop

```bash
git clone https://github.com/svd-ai-lab/sim-plugin-comsol
cd sim-plugin-comsol
uv sync
uv run pytest
```

## License

Apache-2.0. See [LICENSE](LICENSE) and [LICENSE-NOTICE.md](LICENSE-NOTICE.md).
