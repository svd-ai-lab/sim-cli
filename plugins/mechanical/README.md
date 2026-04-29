# sim-plugin-mechanical

[Ansys Mechanical](https://www.ansys.com/products/structures/ansys-mechanical) (PyMechanical) driver for [sim-cli](https://github.com/svd-ai-lab/sim-cli), distributed as an out-of-tree plugin via Python `entry_points`.

## Install

```bash
pip install git+https://github.com/svd-ai-lab/sim-plugin-mechanical@main
```

You also need a working Ansys Mechanical installation on the same host (the `ansys-mechanical-core` SDK launches the local `AnsysWBU.exe`). See [LICENSE-NOTICE.md](LICENSE-NOTICE.md).

After install, sim-cli auto-discovers the driver:

```bash
sim drivers | grep mechanical
sim connect --solver mechanical --mode mechanical --ui-mode gui
```

## How it works

The plugin registers via two entry-point groups:

```toml
[project.entry-points."sim.drivers"]
mechanical = "sim_plugin_mechanical:MechanicalDriver"

[project.entry-points."sim.skills"]
mechanical = "sim_plugin_mechanical:skills_dir"
```

`sim.drivers` exposes the driver class; `sim.skills` exposes a directory of skill files bundled inside the wheel.

The driver launches Mechanical with a **visible GUI window** (`batch=False`) so sim's observation commands (`sim screenshot`, `sim inspect`) can capture the live window. Snippets execute inside Mechanical's IronPython interpreter via `run_python_script`, where `ExtAPI`, `DataModel`, `Model` are all available globals.

## Supported versions

See [`src/sim_plugin_mechanical/compatibility.yaml`](src/sim_plugin_mechanical/compatibility.yaml) for the SDK / solver compatibility matrix. Current profiles cover Mechanical 24.1 / 24.2 / 25.1 / 25.2 against `ansys-mechanical-core` 0.11.x and 0.12.x.

## Develop

```bash
git clone https://github.com/svd-ai-lab/sim-plugin-mechanical
cd sim-plugin-mechanical
uv sync
uv run pytest
```

End-to-end tests require a real Mechanical install; they're gated and skipped when those preconditions are missing.

## Troubleshooting

### `connect` fails with `does not support secure transport modes`

Mechanical < 24.2 has no secure-gRPC support, and 25.2 RTM also lacks it without SP03+. The driver auto-forces insecure transport for < 24.2; for 25.2 RTM (and any future release where you need to opt out of TLS), set:

```bash
export SIM_MECHANICAL_INSECURE_TRANSPORT=1
```

before starting `sim serve` or running `sim connect`. Loopback gRPC traffic stays on the local host, so disabling TLS is benign in the standard sim-cli single-host topology.

## License

Apache-2.0. See [LICENSE](LICENSE) and [LICENSE-NOTICE.md](LICENSE-NOTICE.md).
