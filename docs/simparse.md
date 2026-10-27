# simparse — the parsing engine behind `sim scan`

`sim scan` is powered by [simparse](https://pypi.org/project/simparse/), a
native (Rust) scanner for simulation project and case files. It installs as a
dependency of `sim-cli-core`; no solver, license server or vendor SDK is
needed.

simparse is built for one agent task: look at a file or a folder of historical
simulation work and answer "what is in here?" quickly, before deciding
which heavier vendor tool to call next. It reads metadata, inventories and
setup hints with plain text, ZIP, XML and shallow HDF5 reads, and leaves
geometry, mesh and result payloads where they are, referenced by size and
category.

## What each format reports

| Format | Files | What you get |
|---|---|---|
| COMSOL | `.mph` | File version, model info and tree (`modelinfo.xml`, `dmodel.xml`, `smodel.json`), licenses used, binary blocks by category and size |
| Abaqus | `.inp`, `.inc` | Include graph, node and element counts, materials, sections, steps, boundary and load keywords, output requests |
| Fluent | `.cas.h5`, `.msh.h5` | HDF5 object tree, attributes, dataset shapes and types, zone, boundary and settings hints |
| Ansys Electronics Desktop (HFSS / Icepak) | `.aedt`, `.aedtz` | Product and version, design and solution types, solved status, variables, setups, sweeps, ports, boundaries, materials, mesh operations, lock/result sidecars; for Icepak designs also solution options, ambient conditions, thermal boundaries and powers, monitors, mesh regions |
| Ansys Mechanical | `.mechdb`, `.mechdat` | Release, object and stream counts, analyses, bodies, materials, contacts, loads and conditions, results, geometry sources, sidecar status |
| Icepak Classic | `.tzr` | Project name, entry and file counts, uncompressed size, `job`/`model` payload presence, entry inventory — streamed without extraction |
| Simcenter FloTHERM | `.xml`, `.floxml` (FloXML) | Model and solve options, grid hints, attribute and geometry inventories, heat-source powers, solution-domain boundaries; generic `.xml` is recognised by its root element |
| Simcenter FloTHERM | `.pack` | Project name, sizes, entry counts, presence of project group and base solution, entry inventory |
| Simulink | `.slx`, `.mdl` | Model kind, release, block and library inventory, subsystems, Stateflow usage, root ports, active solver settings |
| MATLAB data | `.mat` (Level 4, v5–v7, v7.3) | Variables with name, class, dimensions and flags, plus header facts |

## Output properties

- **Bounded.** The default summary returns lists as `{total, sample, truncated}`
  and states parser limits explicitly, so a scan over thousands of files stays
  within an agent's context. `sim scan --full` returns the complete result.
- **Privacy-conscious.** Absolute paths are redacted unless `--include-paths` is
  set.
- **Common IR.** Results carry an additive `ir` field in a shared CAE dialect,
  so downstream tools can read one shape across vendors.
- **Fast to call.** A single process start covers a whole directory, which is
  what an agent tool call pays for.

## Platforms and license

Prebuilt wheels: Windows x86_64, macOS Apple silicon, Linux x86_64
(manylinux2014). simparse is free to use, including commercially, under the
simparse License (Copyright SVD Lab); the license ships inside the wheel.

Report parser issues or request a format in
[sim-cli issues](https://github.com/svd-ai-lab/sim-cli/issues) with the
`simparse` label.
