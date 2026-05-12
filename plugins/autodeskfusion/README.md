# sim-plugin-fusion360

Autodesk Fusion 360 driver plugin for `sim`, focused on visible-session
human/AI co-working. Fusion's Python API is available inside the Fusion
process, so this plugin uses a small Fusion add-in bridge instead of a
headless CLI.

Autodesk Fusion 360 is commercial vendor software. This plugin does not bundle
Fusion binaries, Autodesk API stubs, installers, sample projects, licenses, or
activation material; users must install and license Fusion separately. See
[LICENSE-NOTICE.md](LICENSE-NOTICE.md).

## Install

For agent projects, install sim-cli-core and the Fusion 360 plugin in the
project environment:

```powershell
uv init  # only if this is not already a uv project
uv add sim-cli-core "sim-plugin-fusion360 @ git+https://github.com/svd-ai-lab/sim-plugin-fusion360@main"
uv run sim plugin sync-skills --target .agents/skills --copy
uv run sim check fusion360
uv run sim plugin doctor fusion360 --deep
```

For Claude Code, sync the bundled skill to `.claude/skills` instead:

```powershell
uv run sim plugin sync-skills --target .claude/skills --copy
```

`uv run sim ...` runs sim from this project environment, so it sees this
project's plugins. Without uv, create and activate a venv, then install
`sim-cli-core` plus this plugin with `python -m pip`:

```powershell
python -m pip install sim-cli-core "sim-plugin-fusion360 @ git+https://github.com/svd-ai-lab/sim-plugin-fusion360@main"
```

## Scope

- Detect local Fusion installs without launching Fusion.
- Lint Fusion Python scripts with `ast.parse()` without importing `adsk`.
- Install a lightweight `SimFusionBridge` add-in into the user's Fusion API
  AddIns folder.
- Stage Python scripts/snippets into a file-backed queue and receive JSON
  results from the live Fusion session.

Initial smoke target:

```text
../sim-datasets/fusion360/smoke/live_box.py
```

The first live probe created a box in Fusion. The richer live proof created an
approximate iPhone 16 front/back model in the visible Fusion document.

## One-time Fusion setup

Run `uv run sim connect fusion360` or call `Fusion360Driver().launch()` to
install the bridge files. In Fusion, open **Scripts and Add-Ins**, select
`SimFusionBridge`, and run it once. The bridge writes a status heartbeat under
the session directory so the host driver can enqueue work.

## Develop

```bash
git clone https://github.com/svd-ai-lab/sim-plugin-fusion360
cd sim-plugin-fusion360
uv sync --extra test
uv run sim plugin list
uv run sim check fusion360
uv run --extra test pytest --basetemp .pytest_basetemp/local -q
uv build
```

Live integration tests require an interactive desktop session with Fusion
running and the bridge add-in started from Fusion.

## License

Apache-2.0 for the plugin code itself. See [LICENSE](LICENSE) and
[LICENSE-NOTICE.md](LICENSE-NOTICE.md).
