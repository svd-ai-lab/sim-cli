# sim-plugin-comsol

[COMSOL Multiphysics](https://www.comsol.com) driver for [sim-cli](https://github.com/svd-ai-lab/sim-cli), distributed as an out-of-tree plugin via Python `entry_points`.

The COMSOL solver and its `mph` Python binding are not bundled — you supply them yourself. See [LICENSE-NOTICE.md](LICENSE-NOTICE.md).

## Install

```bash
pip install git+https://github.com/svd-ai-lab/sim-plugin-comsol@main
```

After install, sim-cli auto-discovers the driver:

```bash
sim drivers | grep comsol
sim run --solver comsol path/to/script.py
```

## How it works

The plugin registers via two entry-point groups:

```toml
[project.entry-points."sim.drivers"]
comsol = "sim_plugin_comsol:ComsolDriver"

[project.entry-points."sim.skills"]
comsol = "sim_plugin_comsol:skills_dir"
```

`sim.drivers` exposes the driver class; `sim.skills` exposes a directory of skill files bundled inside the wheel.

## Develop

```bash
git clone https://github.com/svd-ai-lab/sim-plugin-comsol
cd sim-plugin-comsol
uv sync
uv run pytest
```

Most tests run without COMSOL installed (they exercise the driver protocol surface against fixtures and use in-memory ZIP archives for the MPH-file probe). The end-to-end tests require a real COMSOL license and are skipped otherwise.

## License

Apache-2.0. See [LICENSE](LICENSE) and [LICENSE-NOTICE.md](LICENSE-NOTICE.md).
