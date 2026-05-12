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

```bash
pip install git+https://github.com/svd-ai-lab/sim-plugin-fusion360@main
```

After install, sim discovers the plugin through Python entry points:

```bash
sim drivers
sim connect fusion360
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

Run `sim connect fusion360` or call `Fusion360Driver().launch()` to install the
bridge files. In Fusion, open **Scripts and Add-Ins**, select
`SimFusionBridge`, and run it once. The bridge writes a status heartbeat under
the session directory so the host driver can enqueue work.

## Develop

```bash
uv sync --extra test
uv run --extra test python -m pytest -q
uv build
```

Live integration tests require an interactive desktop session with Fusion
running and the bridge add-in started from Fusion.

## License

Apache-2.0 for the plugin code itself. See [LICENSE](LICENSE) and
[LICENSE-NOTICE.md](LICENSE-NOTICE.md).
