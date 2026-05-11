# `.mph` file format

`.mph` is a **ZIP archive** (magic bytes `50 4b 03 04`). Confirmed across vendor models in `data/`, `demo/builder/`, and `applications/`. You can read it with stdlib `zipfile` — no `comsolmphserver` JVM required.

## Why this matters

When an agent needs to answer "what's in this `.mph`?" — physics tags, parameters, mesh size, whether it's solved — the historical answer was "spin up a 2 GB JVM." For inspection-only queries that's overkill. The stdlib reader (`sim_plugin_comsol.lib.mph_inspect`) collapses these into sub-second calls and is auto-invoked by the driver's diagnostic probes.

Use this path for saved artifacts and offline diffs. For the current
JPype session, prefer live runtime introspection first:

```bash
uv run sim inspect comsol.model.describe_text
uv run sim inspect comsol.node.properties:<tag-or-dot-path>
```

See `runtime_introspection.md` for the live-session workflow.

## Archive layout

| Entry | Purpose |
|---|---|
| `fileversion` | Single line, e.g. `2092:COMSOL 6.4.0.272` — schema number + saved-in version |
| `modelinfo.xml` | Authoritative metadata (always present): `title`, `description`, `comsolVersion`, `nodeType`, `isRunnable`, `lastComputationTime`, `solvedFileSize`/`compactFileSize` (for previews), `physicsInfo`, `geometryInfo` |
| `dmodel.xml` | Full model tree (compact + solved). Global Parameters live here — see contract below |
| `smodel.json` | Alternate JSON model tree (when present). Recursive `{nodes: [...]}` with `apiClass`, `tag`, `type` — easier to walk than `dmodel.xml`. Application Library models include it; pre-6.x re-saves don't |
| `model.xml` / `fileids.xml` / `clusterignore.xml` / `guimodel.xml` / `auxiliarydatainfo.json` | Smaller manifests |
| `usedlicenses.txt` | One line per required COMSOL module |
| `geometry*.mphbin`, `geommanager*.mphbin` | Geometry binary |
| `mesh*.mphbin`, `xmesh*.mphbin` | Mesh binary |
| `solution*.mphbin`, `solutionblock*.mphbin`, `solutionstatic*.mphbin` | Solver output (solved nodeType only) |
| `savepoint*/...` | Solver checkpoints |
| `modelimage.png`, `modelimage_large.png` | Auto-generated thumbnails |
| `index.txt` + `preview` (0-byte) | Application Library lazy-load placeholder marker |

## Three `nodeType` values

- **`compact`** — settings only, no mesh or solutions. Re-runnable if `isRunnable=true`.
- **`solved`** — full mesh + solution blocks. Largest on disk.
- **`preview`** — Application Library placeholder. Only `modelinfo.xml` + `modelimage.png` present; `index.txt` plus a 0-byte `preview` entry mark it. The full content streams from the gallery on demand.

## Global Parameter contract

Global Parameters in `dmodel.xml`:

```xml
<ModelParam tag="param">
  <ModelParamGroupList>
    <ModelParamGroup tag="default">
      <param T="33" param="L_chamber" value="0.1" reference="chamber length"/>
      <param T="33" param="P_in"      value="101325" reference="inlet pressure"/>
      ...
```

The `T="33"` siblings inside `<ModelParamGroup>` are the global parameters. **Material-level `T="33"` entries exist deeper in the tree** (under material property nodes) and must be excluded — match by parent-element depth, not by attribute alone.

## `smodel.json` optionality

`smodel.json` is shipped by Application Library models but is **dropped on re-save in pre-6.x COMSOL**. Don't depend on it being present; fall back to `dmodel.xml` for the canonical tree.

## Reading the file

The driver ships `sim_plugin_comsol.lib.mph_inspect` with a stdlib-only API:

```python
from sim_plugin_comsol.lib import inspect_mph, MphArchive, mph_diff

# One-shot dict summary
summary = inspect_mph("model.mph")
# → {schema, saved_in, node_type, is_runnable, parameters, physics_tags,
#    study_tags, material_tags, solution_tags, size_breakdown, ...}

# Repeated reads via context manager
with MphArchive("model.mph") as a:
    a.parameters()          # dict of {name: {value, reference}}
    a.physics_tags()        # list[str]
    a.size_breakdown()      # bytes per category (geometry/mesh/solution/...)

# Diff two models (useful for "did my edits actually change anything?")
delta = mph_diff("before.mph", "after.mph")
# → {entries_added, entries_removed, parameters_changed, tags_changed, ...}
```

`MphFileProbe` is wired into the driver's default probe list, so `uv run sim inspect last.result` after a `.mph`-producing step already includes the summary.

## When not to use this

- Anything that needs to *modify* the model. Use the JPype `model.*` API via a live `comsolmphserver`.
- Solver runs. Use `comsolmphserver` + JPype, or (when shipped) `comsolbatch` — see [issue #51](https://github.com/svd-ai-lab/sim-proj/issues/51).
- Geometry/mesh introspection beyond size. The `.mphbin` blocks are opaque without COMSOL's loader.

## References

- Plugin source: [`src/sim_plugin_comsol/lib/mph_inspect.py`](https://github.com/svd-ai-lab/sim-plugin-comsol/blob/main/src/sim_plugin_comsol/lib/mph_inspect.py)
- Reverse-engineering write-up: [sim-proj#51](https://github.com/svd-ai-lab/sim-proj/issues/51), [sim-cli#47](https://github.com/svd-ai-lab/sim-cli/pull/47)
