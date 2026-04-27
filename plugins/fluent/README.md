# sim-plugin-fluent

[Ansys Fluent](https://www.ansys.com/products/fluids/ansys-fluent) (PyFluent) driver for [sim-cli](https://github.com/svd-ai-lab/sim-cli), distributed as an out-of-tree plugin via Python `entry_points`.

## Install

```bash
pip install git+https://github.com/svd-ai-lab/sim-plugin-fluent@main
```

You also need a working Ansys Fluent installation on the same host (the `ansys-fluent-core` SDK launches the local `fluent.exe` / `fluent` binary). See [LICENSE-NOTICE.md](LICENSE-NOTICE.md).

After install, sim-cli auto-discovers the driver:

```bash
sim drivers | grep fluent
sim connect --solver fluent --mode solver --ui-mode gui
```

## How it works

The plugin registers via two entry-point groups:

```toml
[project.entry-points."sim.drivers"]
fluent = "sim_plugin_fluent:PyFluentDriver"

[project.entry-points."sim.skills"]
fluent = "sim_plugin_fluent:skills_dir"
```

`sim.drivers` exposes the driver class; `sim.skills` exposes a directory of skill files bundled inside the wheel.

## Supported versions

See [`src/sim_plugin_fluent/compatibility.yaml`](src/sim_plugin_fluent/compatibility.yaml) for the SDK / solver compatibility matrix. Current profiles cover Fluent 24.1 / 24.2 / 25.1 / 25.2 against `ansys-fluent-core` 0.37.x and 0.38.x.

## Develop

```bash
git clone https://github.com/svd-ai-lab/sim-plugin-fluent
cd sim-plugin-fluent
uv sync
uv run pytest
```

End-to-end tests require a real Fluent install and case file (`SIM_FLUENT_CASE` env var); they're gated and skipped when those preconditions are missing.

## License

Apache-2.0. See [LICENSE](LICENSE) and [LICENSE-NOTICE.md](LICENSE-NOTICE.md).
