# sim-plugin-workbench

[Ansys Workbench](https://www.ansys.com/products/ansys-workbench) (PyWorkbench / RunWB2) driver for [sim-cli](https://github.com/svd-ai-lab/sim-cli), distributed as an out-of-tree plugin via Python `entry_points`.

## Install

```bash
pip install git+https://github.com/svd-ai-lab/sim-plugin-workbench@main
```

You also need a working Ansys Workbench installation on the same host. The driver detects via `AWP_ROOTxxx` env vars, `PATH` (`RunWB2`), and default install dirs. See [LICENSE-NOTICE.md](LICENSE-NOTICE.md).

After install, sim-cli auto-discovers the driver:

```bash
sim drivers | grep workbench
sim run --solver workbench path/to/journal.wbjn
```

## How it works

The plugin registers via two entry-point groups:

```toml
[project.entry-points."sim.drivers"]
workbench = "sim_plugin_workbench:WorkbenchDriver"

[project.entry-points."sim.skills"]
workbench = "sim_plugin_workbench:skills_dir"
```

`sim.drivers` exposes the driver class; `sim.skills` exposes a directory of skill files bundled inside the wheel.

The driver is dual-mode:

1. **PyWorkbench SDK** (`ansys-workbench-core`) — preferred, persistent gRPC session.
2. **RunWB2 batch** (`RunWB2 -B -R journal.wbjn`) — automatic fallback when SDK is unavailable or its `launch_workbench` fails.

IronPython journals write JSON results to `%TEMP%/sim_wb_result.json` because RunWB2 does not pipe stdout.

## Supported versions

See [`src/sim_plugin_workbench/compatibility.yaml`](src/sim_plugin_workbench/compatibility.yaml) for the SDK / solver matrix. Profiles cover Ansys 24.1, 24.2, 25.1, 25.2 against `ansys-workbench-core` 0.4.x through 0.13.x.

## Develop

```bash
git clone https://github.com/svd-ai-lab/sim-plugin-workbench
cd sim-plugin-workbench
uv sync
uv run pytest
```

End-to-end (`@pytest.mark.integration`) tests require a real Workbench install and are skipped otherwise.

## License

Apache-2.0. See [LICENSE](LICENSE) and [LICENSE-NOTICE.md](LICENSE-NOTICE.md).
