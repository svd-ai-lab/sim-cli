# sim-fluent-doc

On-demand search over an installed Ansys Fluent documentation tree. No
browser, no network, no index — just a parallel regex scan over the
static HTML help folders (`flu_ug`, `flu_th`, `flu_udf`, `pyfluent`,
…) that Ansys ships with every install.

## Install

```bash
cd sim-skills/fluent/doc-search
uv sync
```

## Usage

```bash
# Auto-discover the Ansys install and print the doc root
uv run sim-fluent-doc where

# Search
uv run sim-fluent-doc search "turbulence model"
uv run sim-fluent-doc search "k-omega sst" --module flu_th --limit 10

# Scope to the UDF manual
uv run sim-fluent-doc search "udf define_profile" --module flu_udf

# Scope to PyFluent API docs
uv run sim-fluent-doc search "watertight workflow" --module pyfluent

# Dump full page text for a hit
uv run sim-fluent-doc retrieve flu_ug/flu_ug_turbulence.html
```

Searches typically take 1–3 s on a local SSD. Results are ranked by
match count per file.

## How discovery works

`sim-fluent-doc` locates the doc tree in this order:

1. `--ansys-root PATH`
2. `FLUENT_DOC_ROOT` env var (points directly at the help dir)
3. `AWP_ROOT{NNN}` env vars (e.g. `AWP_ROOT252`, `AWP_ROOT251`) — the
   standard Ansys-set variables. If several are present, the highest
   numeric suffix (latest release) wins.
4. `sim check fluent --json` (reuses sim-cli's install discovery)
5. Typical per-OS install paths:
   - Windows: `C:\Program Files\ANSYS Inc\v{NNN}`
   - Linux:   `/usr/ansys_inc/v{NNN}`, `/opt/ansys_inc/v{NNN}`,
     `/ansys_inc/v{NNN}`
   - macOS:   Fluent is not distributed for macOS.

Inside any of those roots the doc tree lives at
`commonfiles/help/en-us/help/`, which contains one subfolder per topic
(`flu_ug`, `flu_th`, `flu_tg`, `flu_udf`, `flu_ml`, `flu_cas`,
`flu_wb2`, `pyfluent`, `wb2_help`, …). Each `.html` file under those
folders is scanned.

## Topic folders (the `--module` filter)

`--module` / `-m` is a substring filter on the topic-folder name.
Common folders:

| Folder      | Contents                                             |
|-------------|------------------------------------------------------|
| `flu_ug`    | Fluent User's Guide                                  |
| `flu_th`    | Theory Guide                                         |
| `flu_tg`    | Tutorial Guide                                       |
| `flu_udf`   | UDF Manual                                           |
| `flu_ml`    | Meshing Manual                                       |
| `flu_cas`   | Customization Manual                                 |
| `flu_wb2`   | Fluent in Workbench                                  |
| `pyfluent`  | PyFluent API docs (when bundled)                     |
| `wb2_help`  | Workbench                                            |

Any direct child directory of the help root is enumerable — vendor
additions and less common `flu_*` / `wb2_*` siblings work too.
