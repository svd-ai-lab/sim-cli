# sim

**`sim` reads existing CAE files and turns them into structured text an agent
can use — without launching the solver.** It also detects local solver installs,
validates scripts before you run them, and can hold a live solver session open
when an agent needs to work one verified step at a time.

Python 3.10+ · Apache-2.0 · alpha

---

## Scan existing simulation assets

Point `sim scan` at a folder of `.mph` / `.inp` / `.cas.h5` / `.aedt` files and
get back structured JSON an agent can reason over — model inventory, materials,
boundary conditions, mesh counts, solve settings. No solver, no license, and no
plugin needed:

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

The default view is bounded — lists come back as `{total, sample, truncated}`
so a large scan cannot blow up an agent's context — and absolute paths are
redacted unless `--include-paths` is set. Use `--full` for the complete parser
result on a small input set, `--limit` and `--no-recursive` to bound a directory
walk, and `--format` to force a format for an explicitly named file.

## Example: what's in this folder?

```text
Scan ./legacy-cases and tell me which models are thermal, which already have
solved results, and which reference materials we no longer have licenses for.
Use `uv run sim --json scan`.
```

## Find solvers and validate scripts

These need the solver's plugin installed — `sim-cli-core` ships with no drivers:

```bash
uv add sim-plugin-comsol
uv run sim plugin sync-skills --target .agents/skills --copy
uv run sim check comsol                    # detect local installs and versions
uv run sim plugin doctor comsol --deep     # plugin wiring + solver detection
uv run sim lint <script>                   # validate before running
```

Use `.agents/skills` for Codex and GitHub Copilot, `.claude/skills` for Claude
Code. Two things are worth telling the agent explicitly: run through the project
with `uv run sim ...` so it sees the project's installed plugins, and never
guess solver API names — inspect the live model or the solver's local docs
first.

No uv, or installing from a wheel, git, or a local checkout — and the `sim.toml`
project manifest schema — are covered in
[docs/plugin-install.md](docs/plugin-install.md).

## Drive a live solver session

When an agent needs the solver held open across steps, `sim connect` starts a
local runtime and keeps the session alive. A bounded step is one modeling,
meshing, solving, or postprocessing action that can be inspected and verified
before continuing: create a geometry feature, assign a material, generate a
mesh, run one study, extract a probe value, export a result table.

Prefer this loop over one large generated script:

1. `uv run sim check <solver>`, then `uv run sim connect --solver <solver>`
2. `uv run sim inspect session.versions` before changing state — including after
   any human GUI edit, since an engineer can cut in through the solver GUI at
   any time and a previous script may no longer match the real session
3. `uv run sim exec --file step.py --label <step>` — one bounded step
4. `uv run sim inspect last.result`, verify with numeric evidence (mesh
   statistics, convergence, probes, conservation checks, tolerances), checkpoint
5. `uv run sim disconnect`, then `uv run sim stop` to free the local runtime

The bundled solver skill enforces the details, so give the agent the engineering
goal in plain language rather than a list of `sim` sub-steps:

```text
Simulate the natural-convection cooling of the attached `pcb.mph` and report the
maximum junction temperature. Use the installed COMSOL skill. If you need a
visible COMSOL Desktop session, connect with `--ui-mode gui`.
```

## Remote solvers

The same machine needs no `--host`. For a solver workstation, lab box, or HPC
login node, install `sim-cli-core` and the plugin there and run:

```bash
# On the solver host.
uv run sim serve --host 0.0.0.0 --port 7600

# On the agent machine.
uv run sim --host <solver-host-ip> connect --solver <solver>
uv run sim --host <solver-host-ip> inspect session.summary
uv run sim --host <solver-host-ip> disconnect
```

**Only bind `sim serve` to a trusted network** such as a VPN, Tailscale, or a
protected LAN. The runtime has no auth layer, and `/connect` plus `/exec` can
execute solver-side code.

## Solver plugins

Solver knowledge is not in the core CLI. It comes from plugins, each of which
provides a **driver**, so `sim` can launch or talk to the solver, and a
**skill**, so the agent knows that solver's workflow, pitfalls, and inspection
rules.

| Solver | Package spec | Plugin repo |
| --- | --- | --- |
| COMSOL | `sim-plugin-comsol` | [sim-plugin-comsol](https://github.com/svd-ai-lab/sim-plugin-comsol) |
| Abaqus | `sim-plugin-abaqus` | [sim-plugin-abaqus](https://github.com/svd-ai-lab/sim-plugin-abaqus) |
| LTspice | `sim-plugin-ltspice` | [sim-plugin-ltspice](https://github.com/svd-ai-lab/sim-plugin-ltspice) |

For the curated full list, see
[sim-plugin-index](https://github.com/svd-ai-lab/sim-plugin-index).

## Commands

Every command takes `--json` and returns a stable envelope with a closed
error-code enum — see [docs/agent-readability.md](docs/agent-readability.md).

| Command | Use it for |
|---|---|
| `uv run sim --json scan <path>...` | Parse historical simulation assets without launching a solver. |
| `uv run sim plugin list` | Show plugins visible in this project environment. |
| `uv run sim plugin info <solver>` | Show plugin metadata and compatibility summary. |
| `uv run sim plugin doctor <solver> --deep` | Check plugin wiring plus local solver detection. |
| `uv run sim plugin sync-skills --target .agents/skills --copy` | Materialize installed plugin skills for your agent. |
| `uv run sim check <solver>` | Detect local or remote solver installs. |
| `uv run sim connect --solver <solver>` | Open a persistent solver session. |
| `uv run sim exec --file step.py` | Run one bounded step in the live session. |
| `uv run sim inspect <target>` | Query session, result, or solver-specific state. |
| `uv run sim run script.py --solver <solver>` | Run a deterministic one-shot script. |
| `uv run sim logs last --field <name>` | Read back a one-shot run's parsed result. |
| `uv run sim disconnect` | Tear down the active session. |
| `uv run sim stop` | Stop the local runtime that `sim connect` auto-started. |
| `uv run sim setup` | Validate `sim.toml` and report declared plugin package specs. |

Run `uv run sim --json describe` for a machine-readable command manifest, or
`uv run sim <command> --help` for exact options.

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
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) — project setup, layout, driver
  protocol, and architecture notes
- [docs/plugin-install.md](docs/plugin-install.md) — plugin installation and
  `sim.toml` reference
- [docs/why-cli-first.md](docs/why-cli-first.md) — why a CLI rather than MCP
- [CONTRIBUTING.md](CONTRIBUTING.md) — branch, test, and PR workflow

## License

Apache-2.0 — see [LICENSE](LICENSE).
