# Offline postprocessing exports

Use this optional pattern when the user asks for COMSOL-free postprocessing,
Python-friendly result artifacts, reusable field data, or analysis after the
COMSOL session is closed. COMSOL is still required once to solve the model and
write the exports. After that, Python tools can read the exported artifacts
without a COMSOL install or license.

This is not a required checkpoint for every solve. Numeric probes remain the
preferred acceptance signal, `inspect_mph()` remains the preferred saved `.mph`
metadata path, and PNG/image exports remain convenience views rather than
primary evidence.

## Recommended artifact bundle

```text
<workdir>/
  model/<case>.mph
  exports/manifest.json
  exports/mph_summary.json
  exports/fields/domain_solution.vtu
  exports/fields/boundary_fields.vtu
  exports/tables/global_metrics.csv
  exports/tables/probes.csv
```

Guidance:

- Use full-domain VTU exports for reusable spatial field data from volume
  domains.
- Use boundary/surface VTU exports for fluxes, walls, terminals, and boundary
  checks.
- Use CSV/TXT exports for probes, global evaluations, cut lines, and scalar
  metrics.
- Use PNG and slice exports only as convenience views, not as the only
  reusable data.
- Do not rely on `.mphbin` for offline postprocessing. Treat it as
  COMSOL-private binary data.
- If no slice exists yet, export the full dataset first. A slice is a useful
  view, but it is a lossy derived artifact.

## Manifest

Write a manifest next to the exported files so an offline reader can interpret
the artifacts without reopening the model:

```json
{
  "model_path": "model/case.mph",
  "comsol_version": "6.4",
  "mph_summary_path": "exports/mph_summary.json",
  "exports": [
    {
      "kind": "field",
      "path": "exports/fields/domain_solution.vtu",
      "dataset": "dset1",
      "level": "volume",
      "expressions": ["T", "ht.fluxMag"],
      "units": ["K", "W/m^2"],
      "time_values": [],
      "parameter_values": {"power": "10[W]"}
    },
    {
      "kind": "field",
      "path": "exports/fields/boundary_fields.vtu",
      "dataset": "dset1",
      "level": "surface",
      "expressions": ["T", "ht.nteflux"],
      "units": ["K", "W/m^2"],
      "time_values": [],
      "parameter_values": {"power": "10[W]"}
    },
    {
      "kind": "table",
      "path": "exports/tables/global_metrics.csv",
      "table": "tbl1",
      "expressions": ["maxop1(T)", "intop1(ht.Q)"],
      "units": ["K", "W"]
    }
  ]
}
```

Useful fields to record:

- Model path and COMSOL version.
- Dataset tag used for each export.
- Expressions and units.
- Export file paths and format.
- Time values, parameter values, or sweep cases.
- Path to the `inspect_mph()` summary for saved `.mph` metadata.

Create the saved `.mph` summary with the stdlib inspector when available:

```python
import json
from pathlib import Path

from sim_plugin_comsol.lib import inspect_mph

summary_path = Path("exports/mph_summary.json")
summary_path.parent.mkdir(parents=True, exist_ok=True)
summary = inspect_mph("model/case.mph")
summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
```

## Headless export snippets

These snippets are for the sim runtime or another already-connected JPype/Java
API context where `model` is provided. Do not call `mph.start()` or create a
second COMSOL client from a snippet. Before using unfamiliar export properties,
inspect the export node with the patterns in
[`java_api_patterns.md`](java_api_patterns.md).

### Full-domain VTU

Use a full-domain VTU for reusable volume/domain fields. Include primary
solved variables and derived quantities that are hard to reconstruct offline,
such as flux magnitude, stress invariants, current density, reaction rates, or
heat sources. Record units in the manifest.

```python
from pathlib import Path
import jpype

out = Path(r"C:\work\case\exports\fields")
out.mkdir(parents=True, exist_ok=True)
jstr = jpype.JArray(jpype.JString)

tag = "exp_domain_vtu"
dataset = "dset1"
exports = model.result().export()
if tag not in list(exports.tags()):
    exports.create(tag, "Data")

exp = model.result().export(tag)
exp.set("filename", str(out / "domain_solution.vtu"))
exp.set("data", dataset)
exp.set("exporttype", "vtu")
exp.set("location", "fromdataset")
exp.set("level", "volume")
exp.set("expr", jstr(["T", "ht.fluxMag"]))
exp.set("unit", jstr(["K", "W/m^2"]))
exp.run()

_result = {
    "export": "domain_solution.vtu",
    "dataset": dataset,
    "level": "volume",
    "expressions": ["T", "ht.fluxMag"],
}
```

### Boundary/surface VTU

Use a surface-level VTU for boundary fields, flux checks, walls, inlets,
outlets, terminals, electrodes, and other boundary-facing review.

```python
from pathlib import Path
import jpype

out = Path(r"C:\work\case\exports\fields")
out.mkdir(parents=True, exist_ok=True)
jstr = jpype.JArray(jpype.JString)

tag = "exp_boundary_vtu"
dataset = "dset1"
exports = model.result().export()
if tag not in list(exports.tags()):
    exports.create(tag, "Data")

exp = model.result().export(tag)
exp.set("filename", str(out / "boundary_fields.vtu"))
exp.set("data", dataset)
exp.set("exporttype", "vtu")
exp.set("location", "fromdataset")
exp.set("level", "surface")
exp.set("expr", jstr(["T", "ht.nteflux"]))
exp.set("unit", jstr(["K", "W/m^2"]))
exp.run()

_result = {
    "export": "boundary_fields.vtu",
    "dataset": dataset,
    "level": "surface",
    "expressions": ["T", "ht.nteflux"],
}
```

### Existing table to CSV

Use table exports for probes, global evaluations, cut lines, and scalar
metrics. This assumes a COMSOL table already exists at `table_tag`.
If the table is created from a numerical feature in the same workflow, set the
intended selection first, assign `table_tag`, then call `setResult()` or
`appendResult()` before exporting. Otherwise COMSOL can write only table
metadata.

```python
from pathlib import Path

out = Path(r"C:\work\case\exports\tables")
out.mkdir(parents=True, exist_ok=True)

tag = "exp_global_metrics_csv"
table_tag = "tbl1"
exports = model.result().export()
if tag not in list(exports.tags()):
    exports.create(tag, "Table")

exp = model.result().export(tag)
exp.set("filename", str(out / "global_metrics.csv"))
exp.set("source", "table")
exp.set("table", table_tag)
exp.set("header", "on")
exp.run()

_result = {
    "export": "global_metrics.csv",
    "table": table_tag,
}
```

## Offline Python readers

Once the exports exist, postprocess them outside COMSOL:

- Read CSV/TXT with the Python standard library, pandas, or polars.
- Read VTU with meshio, pyvista, VTK, or ParaView.
- Keep the manifest with the exported files so downstream ingestion and search
  know which fields, units, dataset, and sweep point each artifact represents.
