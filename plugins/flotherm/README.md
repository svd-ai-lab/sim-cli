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
uv add sim-cli-core "git+https://github.com/svd-ai-lab/sim-plugin-flotherm@main"
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

## Develop

```bash
git clone https://github.com/svd-ai-lab/sim-plugin-flotherm
cd sim-plugin-flotherm
uv sync --extra test
uv run --extra test python -m pytest --basetemp=.tmp/pytest-basetemp
```

Note: Tier-4 (real Flotherm) tests require Windows and a local Flotherm
installation. Tier-1 / Tier-2 tests (detect, lint, FloSCRIPT/FloXML builders)
run on macOS / Linux.

## Windows smoke

Run these from an interactive Windows desktop/RDP session:

```powershell
$sim = ".\.venv\Scripts\sim.exe"
$pack = "C:\Program Files\Siemens\SimcenterFlotherm\2504\examples\Demonstration Models\Superposition\SuperPosition.pack"

& $sim stop
Start-Process -FilePath $sim -ArgumentList "serve","--host","127.0.0.1","--port","7600" -WindowStyle Hidden
& $sim --json connect --solver flotherm --ui-mode no_gui  # expected: unsupported
& $sim --json connect --solver flotherm --ui-mode gui
& $sim --json exec $pack
& $sim --json exec solve
& $sim --json exec status
& $sim disconnect
& $sim stop
```

`exec solve` should return `state: "succeeded"` and `status` should include `solve_log.state: "succeeded"` from `DataSets/BaseSolution/PDTemp/logit`.

## License

Apache-2.0 for the plugin code itself. See [LICENSE](LICENSE) and [LICENSE-NOTICE.md](LICENSE-NOTICE.md).
