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
standalone attach helper:

```powershell
sim-comsol-attach open --json --timeout 120
sim-comsol-attach health --json
sim-comsol-attach exec --file step.java --json
```

Use this path first when the user has COMSOL Desktop open, wants to watch the
model update, or may intervene manually during the session.

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
Use the bundled COMSOL skill in this repository. If COMSOL Desktop is already
open or the user wants visible co-editing, use Desktop attach first. Use the
sim runtime only when structured inspect, driver-managed artifacts, or
server-backed state are needed. Build and solve the requested model one bounded
step at a time.
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
