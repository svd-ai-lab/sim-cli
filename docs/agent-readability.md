# Agent-readability contract

`sim` is invoked mostly by AI agents. Everything in this doc is the contract
those agents rely on. Driver authors and CLI maintainers MUST hold this
contract; users SHOULD know it exists so they can debug behaviour they
don't expect.

The contract has three pillars:

1. **Predictable I/O** — standard flags, stable JSON envelope, closed
   error-code enum.
2. **File-based setup** — no command requires interactive input. Every
   prompt has a flag or config-key equivalent.
3. **Self-describing surface** — `sim describe --json` emits the full CLI
   manifest so an agent can learn the surface from one call.

## 1. Predictable I/O

### Standard top-level flags

| Flag | Meaning |
|---|---|
| `--json` | Emit JSON for the command's primary result. Honoured by every command that returns structured data. |
| `--host <host>` | Override sim-server host (else `SIM_HOST` env, else `localhost`). |
| `--port <port>` | Override sim-server port (else `SIM_PORT` env, else `[server].port` from config, else `7600`). |
| `--session <id>` | Target a specific session (else `SIM_SESSION` env, else server's sole session). |
| `--no-interactive` | Fail fast with `error_code: NONINTERACTIVE_INPUT_REQUIRED` instead of blocking on stdin. Default ON when stdout is not a TTY. |

### JSON envelope

When `--json` is set, every command emits a single top-level JSON object. On
success:

```json
{ "ok": true, ... command-specific keys ... }
```

On failure:

```json
{
  "ok": false,
  "error_code": "<STABLE_CODE>",
  "message": "<human-readable, ≤280 chars>",
  "details": { ... optional structured info ... }
}
```

Long output (stdout, stderr, traces) goes inside `details` or in dedicated
top-level keys (`stdout`, `stderr`); never inside `message`.

### Error codes (closed enum)

| Code | When |
|---|---|
| `SOLVER_NOT_INSTALLED` | The named driver loaded but the underlying solver is not detected on this host. |
| `SOLVER_NOT_DETECTED_FOR_SCRIPT` | A script was given without `--solver` and no driver claimed it. |
| `LINT_FAILED` | `sim lint` produced at least one error-level diagnostic. |
| `RUN_FAILED` | The solver returned non-zero or the driver detected an error in the output. |
| `SESSION_NOT_FOUND` | `--session <id>` does not match any active session on the server. |
| `PLUGIN_NOT_FOUND` | `sim plugin` could not resolve a plugin name (not in the index, no local file). |
| `PLUGIN_INSTALL_FAILED` | `pip install` for a plugin returned non-zero. |
| `PROTOCOL_VIOLATION` | A driver returned a value that doesn't match `DriverProtocol`. |
| `NONINTERACTIVE_INPUT_REQUIRED` | `--no-interactive` is set and the command would otherwise prompt. |

This list is closed: adding a new code requires updating this doc, the CLI,
and the JSON schema emitted by `sim describe --error-codes`.

### Process exit codes

| Code | Meaning |
|---|---|
| 0 | Success. |
| 1 | Run-level failure (solver returned non-zero, lint produced diagnostics). |
| 2 | User error (bad args, unknown command). |
| 3 | Environment error (solver not installed). |
| 4 | Plugin error (`sim plugin install` failed, plugin doctor FAIL). |

`sim plugin doctor --all` exits with a count of FAILed plugins (so it works
in `&&` chains).

## 2. File-based setup

### `sim.toml` schema

A project-level `sim.toml` declares everything an agent needs to drive the
project end-to-end without prompts:

```toml
[sim]
default_solver = "gmsh"
workspace = "./workspace"
server_port = 7600

[[sim.plugins]]
name = "coolprop"
version = ">=0.1.0"

[[sim.plugins]]
name = "gmsh"
git = "https://github.com/svd-ai-lab/sim-plugin-gmsh"
rev = "v0.1.0"

[[sim.plugins]]
name = "local_plugin"
wheel = "./vendor/sim_plugin_local-1.2.0-py3-none-any.whl"   # local, air-gapped
```

`sim init` creates a starter `sim.toml`. `sim setup` reads it and ensures
plugins/server config/workspace are in place. `sim config show --json`
prints the resolved config; `sim config validate <file>` checks a file
against the schema without applying it.

### Resolution order (later overrides earlier)

1. Built-in defaults
2. `~/.config/sim/config.toml` (user-global, alias of `~/.sim/config.toml`)
3. `./.sim/config.toml` and walk-up `./sim.toml` (project)
4. `--config <file>` flag
5. Command-line flags
6. Environment variables (`SIM_*` prefix)

### Sensitive values

Never store secrets in `sim.toml`. Reference env vars instead:

```toml
license_token = "${env:SIM_LICENSE_TOKEN}"
```

The token is resolved at use-time, not load-time; `sim config show` redacts
matching keys by default unless `--unsafe-secrets` is also set.

## 3. Self-describing surface

`sim describe --json` returns the full CLI manifest:

```json
{
  "schema_version": 1,
  "version": "1.0.0",
  "commands": [
    {
      "name": "run",
      "summary": "Execute a script via the appropriate driver.",
      "flags": [...],
      "args": [...],
      "json_output_schema": "RunResult",
      "examples": [
        {"cmd": "sim run examples/sphere.foam --solver openfoam", "summary": "..."}
      ]
    },
    ...
  ],
  "schemas": {
    "RunResult": { ... JSON Schema ... },
    "LintResult": { ... },
    "ConnectionInfo": { ... }
  },
  "error_codes": [...]
}
```

`sim describe <command>` returns just one command's contract.
`sim describe --schema <name>` returns one type's JSON Schema.
`sim describe --error-codes` returns the closed enum.

Agents read this once at session start and route everything else from it.

## Driver-author checklist

Plugin authors implementing `DriverProtocol`:

1. Every public method returns a dict with `"ok": bool` at the top level.
2. On failure, set `"error_code"` from the closed enum and `"message"`
   ≤280 chars. Long output in `"details"` / `"stdout"` / `"stderr"`.
3. `parse_output` returns `{"metrics": {...}, "warnings": [...],
   "diagnostics": [...]}`. Units on every numeric.
4. `detect_installed` is idempotent, ≤500 ms, never imports the SDK.
5. `connect` reports `status` ∈ `{"ok", "not_installed", "error"}`.
6. The driver writes nothing outside its workspace; rely on
   `RunResult.workspace_delta` to surface side effects.
7. Every driver-level config option has a stable key in
   `compatibility.yaml`; settable from `sim.toml` under
   `[sim.driver.<name>]`; never required interactively.
8. The driver's section of `sim describe` is auto-generated from
   `compatibility.yaml` + the driver class docstring.

The pytest fixture `sim.testing.protocol_conformance` checks (1)–(8) for
free; every plugin's CI runs it.
