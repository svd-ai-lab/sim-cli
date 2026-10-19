# sim

**`sim` reads existing CAE files and turns them into structured text an agent
can use — without launching the solver.**

Python 3.10+ · Apache-2.0 · alpha

---

## Scan existing simulation assets

Point `sim scan` at a folder of `.mph` / `.inp` / `.cas.h5` / `.aedt` files and
get back structured JSON an agent can reason over — model inventory, materials,
boundary conditions, mesh counts, solve settings. No solver, no license, and
nothing else to install:

```bash
uv init                  # only if this is not already a uv project
uv add sim-cli-core
uv run sim --json scan ./historical-cases
```

```console
$ uv run sim --json scan ./cases/beam.inp --full
{
  "schema_version": "sim.scan/v1",
  "assets": [{
    "file_name": "beam.inp",
    "format": "abaqus-inp",
    "summary": {"data": {
      "title": "Cantilever beam thermal-stress",
      "node_count": 3,
      "element_count": 1,
      "materials": ["STEEL"],
      "sections": ["SOLID SECTION:STEEL"],
      "steps": ["STATIC"],
      "boundary_keywords": ["BOUNDARY"],
      "load_keywords": ["CLOAD"],
      "output_keywords": ["NODE PRINT"]
    }}
  }]
}
```

(abridged — the real envelope also carries `ok`, `engine`, `request`, and a
roll-up `summary` block.)

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

The default view is bounded — lists come back as `{total, sample, truncated}`
so a large scan cannot blow up an agent's context — and absolute paths are
redacted unless `--include-paths` is set. Use `--full` for the complete parser
result on a small input set, `--limit` and `--no-recursive` to bound a directory
walk, and `--format` to force a format for an explicitly named file.

Every command takes `--json` and returns a stable envelope with a closed
error-code enum — see [docs/agent-readability.md](docs/agent-readability.md).
Run `uv run sim --json describe` for a machine-readable command manifest.

## Example: what's in this folder?

```text
Scan ./legacy-cases and tell me which models are package-level thermal
studies, which already have solved results, and what total power each one
assumes. Use `uv run sim --json scan`.
```

## Optional: working with a local solver

Scanning never needs a solver. If an agent also has to detect solver installs,
lint a script before running it, or keep a solver session open, add that
solver's package (for example `sim-plugin-comsol`) and its agent skill:

```bash
uv add sim-plugin-comsol
uv run sim plugin sync-skills --target .agents/skills --copy   # .claude/skills for Claude Code
uv run sim check comsol
```

The supported solvers, install commands, live-session commands, and the
`sim.toml` manifest are covered in
[docs/plugin-install.md](docs/plugin-install.md). Running the solver on another
host is covered in [docs/remote-solvers.md](docs/remote-solvers.md).

## Solver ownership

`sim-cli` does not bundle or redistribute simulation solvers or vendor SDKs.
Install and operate each underlying solver according to its vendor terms. See
[NOTICE](NOTICE) for optional SDK dependency notes.

`sim-cli` is an independent open-source project and is not affiliated with,
endorsed by, or sponsored by any solver vendor. Product, solver, and company
names remain the property of their respective owners.

## Docs

- [docs/agent-readability.md](docs/agent-readability.md) — `--json` envelope,
  error-code enum, exit codes. Read this first if you are an agent.
- [docs/plugin-install.md](docs/plugin-install.md) — optional solver packages,
  live sessions, and the `sim.toml` reference
- [docs/remote-solvers.md](docs/remote-solvers.md) — running the solver on
  another host, and the security constraints that apply
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) — project setup, layout, driver
  protocol, and architecture notes
- [docs/why-cli-first.md](docs/why-cli-first.md) — why a CLI rather than MCP
- [CONTRIBUTING.md](CONTRIBUTING.md) — branch, test, and PR workflow

## License

Apache-2.0 — see [LICENSE](LICENSE).
