# sim-comsol-doc

On-demand search over an installed COMSOL Multiphysics documentation
tree. No browser, no network, no index — just a parallel regex scan over
the `com.comsol.help.*` Eclipse-help plugins that COMSOL ships on disk.

## Install

```bash
cd src/sim_plugin_comsol/_skills/comsol/doc-search
uv sync
```

## Usage

```bash
# Auto-discover COMSOL and print the doc root
uv run sim-comsol-doc where

# Search
uv run sim-comsol-doc search "battery aging"
uv run sim-comsol-doc search "thermal runaway" --module battery --limit 10

# Scope to Application Gallery example models
uv run sim-comsol-doc search "li plating" --module models.battery

# Dump full page text for a hit
uv run sim-comsol-doc retrieve com.comsol.help.battery/battery_aging.03.01.html
```

Searches typically take 1–3 s on a local SSD (19k files, ~700 MB).
Results are ranked by match count per file.

## How discovery works

`sim-comsol-doc` locates the doc tree in this order:

1. `--comsol-root PATH`
2. `COMSOL_DOC_ROOT` env var (plugin tree)
3. `COMSOL_ROOT` env var (Multiphysics install dir)
4. `sim check comsol --json` (reuses sim-cli's install discovery)
5. Typical per-OS install paths:
   - Windows: `C:\Program Files\COMSOL\COMSOL{NN}\Multiphysics\`
   - macOS:   `/Applications/COMSOL{NN}/Multiphysics/`
   - Linux:   `/usr/local/comsol*/multiphysics/`, `/opt/comsol*/multiphysics/`

Inside any of those roots it expects
`doc/help/wtpwebapps/ROOT/doc/com.comsol.help.*/` — the static XHTML tree
shipped with every COMSOL install.
