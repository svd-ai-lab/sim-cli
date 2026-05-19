# Flotherm post-processing reference

How to extract numeric results from a solved Flotherm project.

There are three paths. Pick the one closest to the result the user needs:

| # | Path | When to use |
|---|---|---|
| A | **FloSCRIPT export commands**, played via GUI Macro→Play | Programmatic extraction; the only headless-friendly path that produces vendor-formatted neutral output. Output formats are **probe-pending** — see §Verification probes. |
| B | **Direct binary read** of `DataSets/BaseSolution/msp_*/end/<Field>` | First pick when the field is one of the 11 cell-centred fields and the user wants raw numbers. No `uv run sim serve`, no GUI, no win1 dependency; runs on any host with the project files. |
| C | **Manual GUI export** (FloVIZ, FloVIEW, Project→Export) | One-off ground truth; not automatable. Use as a tie-breaker if A and B disagree. |

Path A is what you reach for when the user asks for "max-T on the die" or "temperature at the monitor points". Path B is what you reach for when they ask for "the whole 3D field" or raw cell-centred arrays and post-processing is happening in numpy/matplotlib anyway.

---

## Path A — FloSCRIPT export commands

The 2504 FloSCRIPT schema declares 15+ export/save commands. They live in:

- `…\2504\examples\FloSCRIPT\Schema\FloSCRIPTSchema.xsd` — top-level allowed elements
- `…\2504\examples\FloSCRIPT\Schema\CoreFloviewCommands.xsd` — type definitions
- `…\2504\examples\FloSCRIPT\Schema\FloGdaPostFloviewCommands.xsd` — FloGda-specific (plot export)

### Command table

| Command | Type defined in | Required attrs | Required children | Plausible output |
|---|---|---|---|---|
| `<simcenter_field_data_export>` | CoreFloviewCommands.xsd:768 | `filename` | `geometry_name*`, `new_value*`, `save_time*` (all optional) | Simcenter neutral file (`.unv` or similar) — **probe-pending** |
| `<csv_export_attribute>` | CoreFloviewCommands.xsd:330 | `filename` | `<attribute_name>` (1) | CSV (by name) — **probe-pending** |
| `<export_cell_by_cell_results>` | CoreFloviewCommands.xsd:438 | `filename` | `<new_value>` (exactly 2) | Per-cell numeric dump — **probe-pending** |
| `<export_legacy_tables>` | CoreFloviewCommands.xsd:430 | `directory`, `geometry_model`, `grid`, `attributes`, `results` (all bool) | — | Directory of legacy ASCII tables — **probe-pending** |
| `<export_table>` | CoreFloviewCommands.xsd:452 | `filename` | `<table_id>` (1) | Single-table dump — **probe-pending** |
| `<export_transient_table>` | CoreFloviewCommands.xsd:452 (same type) | `filename` | `<table_id>` (1) | Time-series table — **probe-pending** |
| `<export_all_tables>` | FloSCRIPTSchema.xsd:249 | (commonFilenameCommand) `filename` | — | Multi-table dump — **probe-pending** |
| `<export_plot>` | FloGdaPostFloviewCommands.xsd:227 | `filename` | `<results_node_name>` (1) | Plot image / data — **probe-pending** |
| `<assembly_export>` | CoreFloviewCommands.xsd:252 | `filename`, `export_type` | `<geometry_name>` (1) | Geometry-only (not for results) |
| `<project_export>` | CoreFloviewCommands.xsd:674 | `filename`, `export_type` | — | Whole-project (not for results) |
| `<results_state_save_as>` | FloSCRIPTSchema.xsd:187 | (commonFilenameCommand) `filename` | — | Project-state archive |
| `<save_results_setting>` | FloGdaPostFloviewCommands.xsd:127 | `setting_type` ∈ saveType | — | Saved view definition (not data) |
| `<export_floxml>` | FlopackCommands.xsd | (commonFilenameCommand) `filename` | — | Re-emit input as FloXML |
| `<export_compact_model_floxml>` | CCCommands.xsd:424 | `format` ∈ ccExportCompactModelFloxmlFormat | — | Compact-thermal-model FloXML |
| `<export_bci_rom>` | FloSCRIPTSchema.xsd:250 | (many_new_values type) | — | BCI-ROM export |

**The bold "probe-pending"** rows are commands whose output format is undocumented in the install. The vendor ships:
- The XSDs (declares commands exist + their inputs)
- A 2015-vintage `FloSCRIPTv11-Tutorial.pdf` (predates these commands)
- **Zero** demo FloSCRIPT exercising any of them

Output format must be observed by running one — see §Verification probes below.

### How to play an export FloSCRIPT (2504)

`flotherm.exe -f`, `flotherm.bat -f`, and `floserv.exe … -f` all silently drop the script in 2504 (see `known_issues.md` ISSUE-003). The only verified way to play any FloSCRIPT — including export commands — is the GUI macro path:

```
Flotherm GUI → Macro → Play FloSCRIPT → pick file → Open
```

The sim-cli driver automates this via pywinauto UIA + Win32 file dialog. From an agent session:

```bash
uv run sim connect --solver flotherm --ui-mode gui
uv run sim exec '<path>.pack'                       # import + (optionally) solve first
uv run sim exec 'export_temperature.fscript'        # plays the export FloSCRIPT
uv run sim disconnect
```

**Constraint**: a project must already be open and solved. Export commands operate on the in-memory project state, not on a file path argument — there's no `<load_project>` + `<export_*>` chained-from-cold workflow.

> **Driver gap (2026-04-26):** `uv run sim exec` on a FloSCRIPT currently fails with empty dock readback during long solves — see [svd-ai-lab/sim-skills#22](https://github.com/svd-ai-lab/sim-skills/issues/22). For unattended re-solve workflows, use the headless path below instead — it bypasses both the GUI and floserv.

### Headless re-solve (the GUI-free postprocessing path)

For workflows that just need to re-solve an existing project (e.g. parameter sweeps, batch evaluation), call `translator.exe` and `solexe.exe` directly. **No GUI, no floserv, no dock readback**:

```batch
call "<install>\WinXP\bin\flotherm.bat" -env
translator.exe -p "<flouser>\<Project>.<GUID>" -n1
solexe.exe    -p "<flouser>\<Project>.<GUID>"
```

Verified 2026-04-26 on Mobile_Demo_Steady_State (1:41 wall) and HBM_XSD_validation (~25s wall). `solexe.exe` exits with the model's status code — `3` is "normal exit from main program MAINUU" (= converged steady solution).

`tests/inspect/probe_headless_solve.py` in sim-cli automates this round-trip and verifies that field mtime advances + values round-trip through `read_msp_field()`.

**Constraint**: the project must already be in `FLOUSERDIR` (created by a prior GUI session or `project_import`). Initial `.pack` import still requires the GUI today — see `dev-docs/playbook.md` "Flotherm headless batch solve" for the registration prereqs.

---

## Path B — Direct binary read

The solver writes per-field 3D arrays to disk as straightforward little-endian float32 with a 4-byte sentinel header. **Verified 2026-04-26** across four solved projects on Flotherm 2504 (HBM_3block_smoke_v1b, HBM_XSD_validation, HBM_3block_v1b_plus, Mobile_Demo_Steady_State).

> **Use `sim.drivers.flotherm.lib.msp_field` rather than parsing by hand.** Shipped in [svd-ai-lab/sim-cli#43](https://github.com/svd-ai-lab/sim-cli/pull/43):
> ```python
> from sim.drivers.flotherm.lib import read_msp_field, list_fields, read_mesh_dims
> T = read_msp_field(workspace_dir, "Temperature")    # (nz, ny, nx) float32
> ```

The helper is a thin wrapper over `numpy.fromfile` / `numpy.frombuffer` plus
`re.search` against `PDTemp/logit`. If it is not installed on the current
agent, copy the self-contained reader sketch below.

### File layout

```
flouser/<project_name>.<32-hex-hash>/DataSets/BaseSolution/
  PDTemp/logit                         solver residuals + run metadata (text)
  msp_0/end/Temperature                binary: 4-byte header + nx·ny·nz × float32 LE
  msp_0/end/Pressure                   same layout
  msp_0/end/{X,Y,Z}Velocity            same layout
  msp_0/end/Speed                      |velocity|, same layout
  msp_0/end/{X,Y,Z}Conductivity        same layout (anisotropic cell conductivities)
  msp_0/end/FluidConductivity          same layout
  msp_0/end/TurbVis                    same layout (turbulent viscosity field)
```

(`msp_0` = mesh-solve-pass 0, the steady-state or final transient pass; `end` = end-of-pass values.)

**11 fields per case on Flotherm 2504** — confirmed 2026-04-26 across HBM_XSD_validation, HBM_3block_v1b_plus. Earlier versions of this doc listed only 6; the additions are the X/Y/Z/Fluid Conductivities and TurbVis.

### Format details (verified)

- **Header**: 4 bytes, observed value `00 00 00 00` on all 4 sample files. Treat as opaque sentinel; skip 4 bytes and read floats.
- **Body**: exactly `nx·ny·nz` IEEE-754 binary32 little-endian values (file size = `4 + 4·nx·ny·nz`, no trailing record marker — not Fortran-sequential format).
- **Mesh dimensions**: parse from `PDTemp/logit`, line matching `domain 0 no. in x =NN no. in y =NN no. in z =NN`.

Verification table:

| Project | nx·ny·nz | File size | (size−4)/4 | Match |
|---|---|---|---|---|
| HBM_3block_smoke_v1b | 25·29·25 = 18125 | 72504 | 18125 | ✓ |
| HBM_XSD_validation | (= 20000) | 80004 | 20000 | ✓ |
| HBM_3block_v1b_plus | (= 300080) | 1200324 | 300080 | ✓ |
| Mobile_Demo_Steady_State | (= 2907) | 11632 | 2907 | ✓ |

### Cell ordering and units

- **Cell ordering (Fortran vs C / x-fastest vs z-fastest)**: not yet certified. Sample a cell with a known value (e.g. a `<thermal_att thermal_model="fixed_temperature"><fixed_temperature>60</fixed_temperature>` Dirichlet-pinned cuboid) and walk both orderings until the readout matches.
- **Temperature units**: bytes 4–7 of HBM_3block_smoke_v1b decode to ≈44.6, consistent with °C for an unconstrained HBM cell. Sample a Dirichlet-pinned cell to confirm before trusting at scale. (Note the documented FloXML asymmetry: `<fixed_temperature>` is °C, `<ambient_att><temperature>` is K — see [`floxml_authoring.md` §Unit gotcha](floxml_authoring.md#unit-gotcha-verified-2026-04-19-on-flotherm-2504-fixed_temperature-value-is-in-c-not-k).)

### Reader sketch (numpy)

```python
import numpy as np
import re
from pathlib import Path

def read_field(project_dir: Path, field: str = "Temperature", msp: int = 0) -> np.ndarray:
    ds = project_dir / "DataSets" / "BaseSolution"
    logit = (ds / "PDTemp" / "logit").read_text(errors="replace")
    m = re.search(r"domain 0 no\. in x\s*=(\d+)\s*no\. in y\s*=(\d+)\s*no\. in z\s*=(\d+)", logit)
    if not m:
        raise RuntimeError("could not parse mesh dims from PDTemp/logit")
    nx, ny, nz = (int(g) for g in m.groups())
    raw = (ds / f"msp_{msp}" / "end" / field).read_bytes()
    expected = 4 + 4 * nx * ny * nz
    if len(raw) != expected:
        raise RuntimeError(f"size mismatch: got {len(raw)}, expected {expected} (nx*ny*nz={nx*ny*nz})")
    return np.frombuffer(raw, dtype="<f4", offset=4).reshape((nz, ny, nx))  # ordering TBD; see note
```

Reshape ordering above is `(nz, ny, nx)` — i.e. assumes x-fastest. Flip if the Dirichlet-cell sanity check fails.

### When binary read isn't enough

- You need values **at named geometry** (a cuboid, a monitor point) rather than at grid cells. Geometry-aware reduction needs FloVIEW, i.e. Path A.
- You need values **on cell faces** (heat flux through a surface). The `msp_*/end/` files are cell-centred field values — face fluxes have to come from a FloSCRIPT export.
- You need **transient histories**, not just an end-state snapshot. Time-series come from `<export_transient_table>` (Path A) or by reading every transient `msp_<i>/<time>/` directory yourself.

---

## Path C — Manual GUI export

`Project → Export → ...` menu in the Flotherm GUI, or `Tools → FloVIZ → File → Export` from the post-processor. Output formats are documented in vendor PDFs we don't have. Useful as a tie-breaker for ground truth — open the GUI, do the export by hand, see what it wrote, then encode that in a Path-A FloSCRIPT.

---

## Verification probes

Copy-paste FloSCRIPT files for filling in the "probe-pending" rows in §Path A. Each probe assumes a project is already loaded and solved (e.g. via `uv run sim exec '<path>.pack'` → `uv run sim exec 'solve'`). Run with:

```bash
uv run sim exec '<probe>.fscript'
```

After the play, inspect the named output file: extension, size, first 256 bytes, and whether it parses as the expected format.

### probe-csv-export.fscript

Asks for one named attribute as CSV. Replace `<attribute_name>` with one that exists in the loaded project (e.g. `Temperature` is the safest guess — confirm via the GUI's attribute list).

```xml
<?xml version="1.0" encoding="UTF-8"?>
<xml_log_file version="1.0">
  <csv_export_attribute filename="C:/temp/probe_csv_export.csv">
    <attribute_name>Temperature</attribute_name>
  </csv_export_attribute>
</xml_log_file>
```

Expected: `C:/temp/probe_csv_export.csv` exists. Inspect with `Get-Content -TotalCount 5 C:/temp/probe_csv_export.csv` to learn column layout.

### probe-legacy-tables.fscript

Dumps the whole result set as the old text-table format. The closest 2504 has to "give me everything human-readable".

```xml
<?xml version="1.0" encoding="UTF-8"?>
<xml_log_file version="1.0">
  <export_legacy_tables directory="C:/temp/probe_legacy"
                        geometry_model="true"
                        grid="true"
                        attributes="true"
                        results="true"/>
</xml_log_file>
```

Expected: `C:/temp/probe_legacy/` populated with text files. List with `Get-ChildItem C:/temp/probe_legacy -Recurse | Select Name, Length`.

### probe-simcenter-field-export.fscript

Vendor-neutral 3D field export. Most likely the right path for "give me the temperature field as a file numpy can read without parsing PDTemp/end binaries".

```xml
<?xml version="1.0" encoding="UTF-8"?>
<xml_log_file version="1.0">
  <simcenter_field_data_export filename="C:/temp/probe_simcenter.unv"/>
</xml_log_file>
```

Expected: a file named `probe_simcenter.unv` (or whatever extension Flotherm picked — the schema doesn't constrain it; the path attribute is `xs:string`). Inspect first 256 bytes; if it's ASCII starting with `-1` and structured into 8-column groups, it's I-DEAS Universal File format and can be read with `pyvista.read()` or a UNV parser.

### probe-cell-by-cell.fscript

Per-cell numeric dump. Requires exactly 2 `<new_value>` children — the schema doesn't document what they bind to (likely "from time" and "to time" for a transient diff, but verify).

```xml
<?xml version="1.0" encoding="UTF-8"?>
<xml_log_file version="1.0">
  <export_cell_by_cell_results filename="C:/temp/probe_cell_by_cell.csv">
    <new_value>0</new_value>
    <new_value>1</new_value>
  </export_cell_by_cell_results>
</xml_log_file>
```

Expected: `C:/temp/probe_cell_by_cell.csv`. The 2-child constraint is unusual; if this rejects with E/15002 in the GUI Message Window, screenshot the message and update this probe.

---

## Open questions

- **Which export gives `(x, y, z, T)` rows directly?** Hypothesis: `<csv_export_attribute>` for "all cells of attribute `Temperature`". To be confirmed.
- **What does `<simcenter_field_data_export>` actually write?** Hypothesis: `.unv` (I-DEAS Universal File). Plausible alternates: `.ssa` (Simcenter STAR neutral) or a Siemens-specific binary.
- **Can `<export_transient_table>` produce monitor-point time-series in one command?** Probably yes via the `<table_id>` referencing a monitor-point report table, but the table-id naming convention isn't in the schema.
- **Is there a "save view + screenshot" pair that produces a PNG of a contour plot?** `<export_plot>` is the candidate but the output type isn't constrained — probe to find out.

When a probe fills in one of these gaps, update the relevant row in §Path A's command table from "probe-pending" to the verified format, and add the probe FloSCRIPT to `base/workflows/postprocess_*.fscript` for reuse.
