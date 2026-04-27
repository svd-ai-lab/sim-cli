# sim-plugin-abaqus

[Dassault Systemes SIMULIA Abaqus](https://www.3ds.com/products/simulia/abaqus) driver for [sim-cli](https://github.com/svd-ai-lab/sim-cli), distributed as an out-of-tree plugin via Python `entry_points`.

## Install

```bash
pip install git+https://github.com/svd-ai-lab/sim-plugin-abaqus@main
```

You also need a working Abaqus installation on the same host (the driver invokes `abaqus.bat` / `abqNNNN.bat` via subprocess). See [LICENSE-NOTICE.md](LICENSE-NOTICE.md).

After install, sim-cli auto-discovers the driver:

```bash
sim drivers | grep abaqus
sim run --solver abaqus path/to/job.inp
sim run --solver abaqus path/to/cae_script.py
```

## How it works

The plugin registers via two entry-point groups:

```toml
[project.entry-points."sim.drivers"]
abaqus = "sim_plugin_abaqus:AbaqusDriver"

[project.entry-points."sim.skills"]
abaqus = "sim_plugin_abaqus:skills_dir"
```

`sim.drivers` exposes the driver class; `sim.skills` exposes a directory of skill files bundled inside the wheel.

Execution is pure subprocess — the driver never imports Abaqus internals (which live in Abaqus's own embedded Python, not the system Python):

- Input decks (`.inp`): `abaqus job=<name> input=<file> interactive`
- CAE Python scripts (`.py`): `abaqus cae noGUI=<file>`

## Supported versions

See [`src/sim_plugin_abaqus/compatibility.yaml`](src/sim_plugin_abaqus/compatibility.yaml) for the version matrix. The current profile covers Abaqus 2026.

## Develop

```bash
git clone https://github.com/svd-ai-lab/sim-plugin-abaqus
cd sim-plugin-abaqus
uv sync
uv run pytest
```

End-to-end tests require a real Abaqus install; they're gated and skipped when Abaqus is not detected on the host.

## License

Apache-2.0. See [LICENSE](LICENSE) and [LICENSE-NOTICE.md](LICENSE-NOTICE.md).
