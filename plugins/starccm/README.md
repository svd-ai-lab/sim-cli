# sim-plugin-starccm

[Simcenter STAR-CCM+](https://plm.sw.siemens.com/en-US/simcenter/fluids-thermal-simulation/star-ccm/) driver for [sim-cli](https://github.com/svd-ai-lab/sim-cli), distributed as an out-of-tree plugin via Python `entry_points`.

STAR-CCM+ has no pip-installable Python SDK. Scripts are Java macros (`.java` files extending `StarMacro`) executed through `starccm+ -batch`. The user must install and license STAR-CCM+ separately. See [LICENSE-NOTICE.md](LICENSE-NOTICE.md).

## Install

```bash
pip install git+https://github.com/svd-ai-lab/sim-cli.git@main#subdirectory=plugins/starccm
```

After install, sim-cli auto-discovers the driver:

```bash
sim drivers | grep starccm
sim run --solver starccm path/to/macro.java
```

## How it works

The plugin registers via two entry-point groups:

```toml
[project.entry-points."sim.drivers"]
starccm = "sim_plugin_starccm:StarccmDriver"

[project.entry-points."sim.skills"]
starccm = "sim_plugin_starccm:skills_dir"
```

`sim.drivers` exposes the driver class; `sim.skills` exposes a directory of skill files bundled inside the wheel.

## Supported versions

See [`src/sim_plugin_starccm/compatibility.yaml`](src/sim_plugin_starccm/compatibility.yaml) for the solver compatibility matrix. Current profile covers STAR-CCM+ 21.02 (a.k.a. 2602).

## License

Apache-2.0. See [LICENSE](LICENSE) and [LICENSE-NOTICE.md](LICENSE-NOTICE.md).
