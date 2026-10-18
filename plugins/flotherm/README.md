# sim-plugin-flotherm

[Simcenter Flotherm](https://plm.sw.siemens.com/en-US/simcenter/mechanical-simulation/flotherm/) driver for [sim-cli](https://github.com/svd-ai-lab/sim-cli), distributed as an out-of-tree plugin via Python `entry_points`.

This plugin does not bundle Flotherm, vendor binaries, or vendor SDKs. See
[LICENSE-NOTICE.md](LICENSE-NOTICE.md).

The driver is Windows-only — Flotherm itself only ships on Windows, and the driver uses `pywinauto` GUI automation (Flotherm has no headless batch API for first-time project setup).

## Install

For agent projects, install sim-cli-core and the Flotherm plugin in the project
environment:

```powershell
uv init  # only if this is not already a uv project
uv add sim-cli-core "git+https://github.com/svd-ai-lab/sim-cli/tree/main/plugins/flotherm@main"
uv run sim plugin sync-skills --target .agents/skills --copy
uv run sim check flotherm
uv run sim plugin doctor flotherm --deep
```

For Claude Code, sync the bundled skill to `.claude/skills` instead:

```powershell
uv run sim plugin sync-skills --target .claude/skills --copy
```

`uv run sim ...` runs sim from this project environment, so it sees this
project's plugins. Without uv, create and activate a venv, then install
`sim-cli-core` plus this plugin with `python -m pip`.

## How it works

The plugin registers via two entry-point groups:

```toml
[project.entry-points."sim.drivers"]
flotherm = "sim_plugin_flotherm:FlothermDriver"

[project.entry-points."sim.skills"]
flotherm = "sim_plugin_flotherm:skills_dir"
```

`sim.drivers` exposes the driver class; `sim.skills` exposes a directory of skill files bundled inside the wheel (workflows, FloSCRIPT XSD schemas, version-specific quirks).

## License

Apache-2.0 for the plugin code itself. See [LICENSE](LICENSE) and [LICENSE-NOTICE.md](LICENSE-NOTICE.md).
