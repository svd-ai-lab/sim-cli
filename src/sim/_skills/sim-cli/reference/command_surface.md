# sim-cli command surface

This is the canonical reference for `sim …` subcommands. Verified
against `sim-cli/src/sim/cli.py`. If a driver skill or downstream doc
disagrees, this file wins — fix the downstream doc.

---

## Global options (all commands)

```
sim [--host HOST] [--port PORT] [--json] <command> …
```

- `--host` — defaults to `localhost`. Use for remote `sim serve`
  instances (e.g. a Windows box over Tailscale).
- `--port` — defaults to `8765`.
- `--json` — machine-readable output. Prefer when parsing in snippets;
  human output is for terminals.

---

## One-shot execution

### `sim run <script> --solver <solver>`

Executes a script in a subprocess and exits. No persistent session. The
driver's `parse_output(stdout)` extracts the JSON payload, which is
returned on the `parsed_output` field in `--json` mode.

```bash
sim run analysis.py --solver example
sim run job.in     --solver example_batch
```

**Exit code**: 0 if the driver reports `ok=true`, non-zero otherwise.
**Use for**: drivers that have no persistent-session model.

---

## Persistent session

### `sim serve [--host HOST] [--port PORT] [--reload]`

Starts the HTTP server. Usually launched once per host; `sim connect`
on a local host auto-starts a server if none is running. Run manually
for remote boxes.

### `sim connect --solver <solver> [--mode MODE] [--ui-mode UI] [--processors N] [--workspace PATH] [--driver-option KEY=VALUE]...`

Launches the solver inside the server and holds a session open.
Core launch flags:

| Flag | Drivers that use it |
|---|---|
| `--mode <mode>` | drivers with multiple runtime modes |
| `--ui-mode gui \| no_gui` | GUI-capable drivers |
| `--processors N` | any MPI-capable solver |
| `--workspace PATH` | drivers with a run/work directory concept |
| `--driver-option KEY=VALUE` | generic plugin-owned launch option passthrough; repeat as needed |

`--driver-option` is intentionally opaque to sim-cli. The driver skill
documents which keys its driver accepts, what the defaults mean, and how
the plugin validates or translates them. Keep solver-specific launch
settings here instead of inventing new top-level sim-cli flags.

### `sim exec [<code>] [--file PATH] [--label LABEL]`

Runs a snippet inside the live session. Pass code as a positional arg,
or read from a file with `--file`. `--label` is free-text; it shows up
in `session.summary.run_count` and log files — use descriptive labels
like `import-geometry`, `hybrid-init`.

```bash
sim exec --file 03_setup_physics.py --label setup-physics
sim exec "model.mesh.check()"       --label mesh-check
```

**Exit code**: 0 if the snippet's `ok=true`, `2` on `ok=false`.

### `sim inspect <target>`

Queries live session state. Common targets across all drivers:

| Target | Returns |
|---|---|
| `session.summary` | `connected`, `mode`, `run_count` |
| `session.versions` | `sdk`, `solver`, `profile`, `active_sdk_layer`, `active_solver_layer`, `env_path` — **use at Step 0** |
| `session.mode` | Current session mode (driver-dependent) |
| `last.result` | `ok`, `label`, `result`, `stdout`, `stderr` from the most recent `exec` |
| `workflow.summary` | Workflow task states, when exposed by a driver |
| `field.catalog` | Available fields for post-processing, when exposed by a driver |

Driver-specific targets are documented in each driver skill's SKILL.md
and may include additional namespaces.

### `sim disconnect [--stop-server]`

Tears down the solver session. By default the server keeps running so
subsequent `connect` calls are instant. `--stop-server` also kills the
server (equivalent to `sim stop` afterwards).

---

## Housekeeping

| Command | Purpose |
|---|---|
| `sim ps` | List active sessions on the server |
| `sim stop` | Stop the running server |
| `sim check <solver>` | On-demand driver detection without holding a session |

---

## Common drift to avoid

These are mistakes found in existing driver skills — do not repeat:

- `sim query …` → it is **`sim inspect …`**. `query` was the old name;
  the current CLI does not expose `query` as a subcommand.
- `sim exec --code-file PATH` → it is **`sim exec --file PATH`**. There
  is no `--code-file` flag.
- `sim run … --solver <name>` **cannot take `--mode`**. Mode is a
  persistent-session concept (`sim connect --mode …`).
