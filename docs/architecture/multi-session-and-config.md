# Multi-Session + Config — Shared Schema Design

> Status: **design note, used as the implementation contract for issues
> [#5](https://github.com/svd-ai-lab/sim-cli/issues/5) (two-tier config +
> global history) and [#26](https://github.com/svd-ai-lab/sim-cli/issues/26)
> (multi-session `sim serve`).**
>
> Purpose: pin the shared schema (history record shape, log line format,
> config resolution, `/ps` shape, session selector) once, so either issue
> can land first without the other renegotiating anything.

## 1. Scope of this note

These are the only surfaces the two issues share. Everything else is
independent and decided inside each PR.

| Surface | Owned by | Multi-session impact |
|---|---|---|
| `history.jsonl` schema | #5 | Reserves `session_id`, `solver` fields |
| `sim-serve.log` line format | #5 | Requires `[session=<id>]` prefix |
| `sim logs` filters | #5 | Adds `--session`, `--solver` flags |
| Config resolution order | #5 | Re-specified to be solver-aware |
| `/ps` response shape | #26 | Breaking change, decided here |
| Session selector on the wire | #26 | Header-only (decision here) |
| Default session behaviour | #26 | "Only session" default + env + flag |

## 2. `history.jsonl` record shape

One JSON object per line. **All fields present even when unused** (null /
empty string) so downstream tools can rely on column presence.

```json
{
  "ts": "2025-04-24T07:21:14Z",
  "cwd": "/abs/path/to/project",
  "session_id": "s-8f3a",
  "solver": "fluent",
  "run_id": "r-0001",
  "kind": "exec",
  "label": "cli-snippet",
  "ok": true,
  "duration_ms": 142,
  "error": null
}
```

Field rules:

- `ts` — UTC, ISO-8601 with trailing `Z`.
- `cwd` — absolute path of the **caller's** working directory, not the
  server's. (`sim exec` from `~/foo` logs `~/foo`, not `.sim/`.)
- `session_id` — set when a session exists (`sim exec`, `sim run` when
  routed through a session). For `sim run <file>` one-shot (no server,
  no session), `session_id` is the empty string `""`. Never `null`.
- `solver` — driver name (`fluent`, `mapdl`, `pybamm`, ...). For one-shot
  `sim run`, this is the driver used.
- `run_id` — monotonic id, unique within a process. Opaque string.
- `kind` — one of `exec`, `run`, `run_file`. (`run` = `sim run <file>`
  one-shot; `run_file` = server-side `/run` via a session; `exec` = code
  snippet via a session.)
- `ok` / `error` — `ok=false` with `error` as a short string when
  parsed-output marks the run as failed.

**Append-only**, no rotation in v1. `sim logs --tail N` reads from the
end. If the file grows unpleasantly we can add rotation later; the
record shape doesn't need to change for that.

## 3. `sim-serve.log` line format

```
2025-04-24T07:21:14Z [session=s-8f3a] [solver=fluent] /exec cli-snippet ok (142 ms)
```

Prefix rules:

- Always `[session=<id>]` even when only one session is live.
- `[solver=<name>]` added after `session=`.
- Lines **not tied to a session** (server startup, shutdown, unknown
  session errors) omit both prefixes — they are global.

This is plain human-readable logging, not structured. Parsing is not a
goal. The prefix exists so `grep 'session=s-8f3a'` works.

## 4. Config resolution

Resolution order, earliest wins:

```
env var  >  project .sim/config.toml  >  global ~/.sim/config.toml  >  auto-detect / hardcoded default
```

Under multi-session, the schema is unchanged but two UX rules apply:

1. **Solver pins are advisory, not gating.** If
   `.sim/config.toml` pins `[solvers.fluent]` but the user runs
   `sim connect --solver mapdl`, the connect proceeds; the pin is
   ignored for that session and a one-line warning is printed. Rationale:
   a project may legitimately run Mechanical + Flotherm side by side.
2. **`sim connect` with no `--solver` picks the one pinned default if
   present; otherwise errors with the available driver list.** No
   guessing across multiple pins.

## 5. `/ps` response shape

Breaking change — migrate once, don't carry two shapes.

```json
{
  "sessions": [
    {
      "session_id": "s-8f3a",
      "solver": "fluent",
      "mode": "meshing",
      "ui_mode": "no_gui",
      "processors": 1,
      "connected_at": "2025-04-24T07:18:02Z",
      "run_count": 3,
      "profile": "pyfluent-0.38"
    }
  ],
  "default_session": "s-8f3a",
  "server_pid": 12345
}
```

Notes:

- `sessions` is `[]` when no sessions are live. No separate `connected`
  boolean.
- `default_session` is the id that applies when a client sends no
  selector (see §6). `null` if no sessions live.
- CLI `sim ps` renders the list as a table, marks the default row.
- Because this is a breaking change, the CLI client updates in the same
  PR as the server. The `session.py` `SessionClient.status()` caller in
  `cli.py` is the only code path to update.

## 6. Session selector on the wire

**Header-only.** `X-Sim-Session: <id>` on every per-session endpoint
(`/exec`, `/inspect/<name>`, `/disconnect`, `/screenshot`, `/run`).
Query-param form is not accepted. One way to do it, simpler to test.

Server-side default-picking rules, in order:

1. If `X-Sim-Session` header present → use it. 404 if unknown.
2. Else if exactly one session live → use it. (The "only session" rule —
   preserves current CLI ergonomics when a user isn't juggling sessions.)
3. Else → 400 `"multiple sessions live, set X-Sim-Session or use --session"`.

Client-side (`sim` CLI) default-picking rules:

1. `--session <id>` flag if passed.
2. Else `SIM_SESSION` env var if set.
3. Else no header — let the server apply rule (2) or (3).

We deliberately do **not** persist a "current session" file on disk.
Rationale: cheap to type the id, removes a stale-state foot-gun, makes
agent-driven flows deterministic.

## 7. Concurrency

- Each `SessionState` carries its own `threading.Lock`.
- `/exec` acquires that session's lock. Two sessions can run `/exec`
  concurrently; two calls to the same session serialize.
- `/shutdown` tears down **all** sessions in the order they were
  created, then exits.
- Drivers are not thread-safe globally, but different driver instances
  for different solvers are independent by assumption — this is
  already how `sim serve` is used today, just with n=1.

## 8. Filesystem layout after both land

```
~/.sim/
    config.toml           # global config (#5)
    history.jsonl         # global run history (#5)

<project>/.sim/
    config.toml           # project config (#5)
    sim-serve.log         # server log, [session=*] prefixed (#5 + #26)
    envs/                 # profile envs (unchanged)
    # NOTE: no runs/ subdir — history moved to ~/.sim/history.jsonl
    # NOTE: no current_session file — by design (§6)
```

## 9. Landing order

Either order works. Recommended: **#5 first** (purely additive on the
server side; `history.jsonl` records for one-shot `sim run` can land
with `session_id=""` immediately), **#26 second** stacked on top
(breaking `/ps` shape, adds header routing).

If #26 lands first in isolation, it must still write the full record
shape from §2, with `cwd` and `solver` fields populated, so #5 can turn
`sim logs` on without a data migration.

## 10. Non-goals

- Auth, per-user isolation, resource caps, cross-session IPC helpers.
- Log rotation, log level config.
- Multi-user `history.jsonl` (still a single trust domain).
- Versioning the `history.jsonl` schema — add a `version` field the
  first time we need to change it, not preemptively.
