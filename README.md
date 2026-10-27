# sim

**`sim` reads existing CAE files and turns them into structured text an agent
can use — without launching the solver.**

Python 3.10+ · Apache-2.0 · alpha

```bash
uv init                  # only if this is not already a uv project
uv add sim-cli-core
uv run sim --json scan ./historical-cases
```

One call covers a whole folder. No solver, no license server, no vendor SDK.
Output is bounded so a large scan fits in an agent's context, and absolute
paths are redacted by default.

```console
$ uv run sim --json scan ./cases/beam.inp --full
{"schema_version": "sim.scan/v1",
 "assets": [{"file_name": "beam.inp", "format": "abaqus-inp",
   "summary": {"data": {"title": "Cantilever beam thermal-stress",
     "node_count": 3, "element_count": 1, "materials": ["STEEL"],
     "steps": ["STATIC"], "boundary_keywords": ["BOUNDARY"],
     "load_keywords": ["CLOAD"], "output_keywords": ["NODE PRINT"]}}}]}
```

(abridged — the full envelope also carries `ok`, `engine`, `request` and a
roll-up `summary`.)

## Supported files

| Solver | Files | `--format` id |
| --- | --- | --- |
| COMSOL | `.mph` | `comsol-mph` |
| Abaqus | `.inp`, `.inc` | `abaqus-inp` |
| Fluent | `.cas.h5`, `.msh.h5` | `fluent-hdf5` |
| Ansys Electronics Desktop (HFSS / Icepak) | `.aedt`, `.aedtz` | `hfss-aedt` |
| Ansys Mechanical | `.mechdb`, `.mechdat` | `ansys-mechanical` |
| Icepak Classic | `.tzr` | `icepak-tzr` |
| Simcenter FloTHERM | `.pack`, `.xml`, `.floxml` | `flotherm-pack`, `flotherm-floxml` |
| Simulink | `.slx`, `.mdl` | `simulink-slx`, `simulink-mdl` |
| MATLAB data | `.mat` | `matlab-mat` |

What each format reports: [docs/simparse.md](docs/simparse.md).

## Options

| Flag | Effect |
| --- | --- |
| `--full` | Complete parser result instead of the bounded summary (small input sets) |
| `--include-paths` | Keep absolute source paths |
| `--limit N`, `--no-recursive` | Bound a directory walk |
| `--format ID` | Force a format for an explicitly named file |

Every command takes `--json` and returns a stable envelope with a closed
error-code enum. `uv run sim --json describe` prints the full command manifest.

## Docs

- [docs/agent-readability.md](docs/agent-readability.md) — JSON envelope,
  error codes, exit codes. Read this first if you are an agent.
- [docs/simparse.md](docs/simparse.md) — what each file format reports.
- [docs/plugin-install.md](docs/plugin-install.md) — optional solver packages
  for detecting installs and driving a live solver session.
- [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## License

Apache-2.0 — see [LICENSE](LICENSE). Solvers are not bundled; vendor and
trademark notes are in [NOTICE](NOTICE).
