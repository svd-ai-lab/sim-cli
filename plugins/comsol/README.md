# sim-plugin-comsol

[COMSOL Multiphysics](https://www.comsol.com) driver for [sim-cli](https://github.com/svd-ai-lab/sim-cli), distributed as an out-of-tree plugin via Python `entry_points`.

The COMSOL solver and its `mph` Python binding are not bundled — you supply them yourself. See [LICENSE-NOTICE.md](LICENSE-NOTICE.md).

## Install

```bash
pip install sim-plugin-comsol
```

After install, sim-cli auto-discovers the driver:

```bash
sim drivers | grep comsol
sim run --solver comsol path/to/script.py
```

You can also install through sim-cli's plugin command:

```bash
sim plugin install sim-plugin-comsol
```

For realtime-visible COMSOL Desktop collaboration on Windows, use the
standalone attach helper:

```powershell
sim-comsol-attach open --json --timeout 120
sim-comsol-attach exec --file step.java --json
```

## How it works

The plugin registers via three entry-point groups:

```toml
[project.entry-points."sim.drivers"]
comsol = "sim_plugin_comsol:ComsolDriver"

[project.entry-points."sim.skills"]
comsol = "sim_plugin_comsol:skills_dir"

[project.entry-points."sim.plugins"]
comsol = "sim_plugin_comsol:plugin_info"
```

`sim.drivers` exposes the driver class; `sim.skills` exposes a directory
of skill files bundled inside the wheel; `sim.plugins` exposes plugin
metadata for discovery.

## Develop

```bash
git clone https://github.com/svd-ai-lab/sim-plugin-comsol
cd sim-plugin-comsol
uv sync
uv run pytest
```

## License

Apache-2.0. See [LICENSE](LICENSE) and [LICENSE-NOTICE.md](LICENSE-NOTICE.md).
