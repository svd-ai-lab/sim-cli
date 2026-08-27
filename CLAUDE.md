# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**sim** reads existing CAE files and turns them into structured text an agent can use, detects local solver installs, validates scripts, and can hold a live solver session open across steps. The `pyproject.toml` description — "Agent-native simulation asset parsing and CAD/CAE runtime" — states the priority correctly: parsing first, runtime second.

**Know which tier you are working in, because their dependencies differ:**

- **Asset parsing** (`sim scan`) — pure core, no plugin, no solver, no license. Backed by the `simparse` native extension, a hard dependency of `sim-cli-core`. This is the most-used capability in practice: agents can already drive solver GUIs directly, so the highest-value thing `sim` does today is recover engineering context from historical case files (a preprocessing step, closer to a document-to-structured-text converter than to a solver driver).
- **Solver discovery and script validation** (`sim check`, `sim lint`) — require the solver's plugin. With no plugins installed, `check --all` reports "scanned 0 drivers" and `lint` errors with `No registered driver claims ...`.
- **Execution** — requires a plugin, and comes in two modes:
  - **One-shot** (`sim run script --solver=X`): subprocess execution, result stored as a numbered run, `sim logs` to browse.
  - **Persistent session** (`sim connect/exec/inspect/disconnect`): a long-lived HTTP server holds a live solver session; agents send code snippets and inspect state without restarting the solver. `sim connect` auto-starts a local server when none is reachable (`session.py:_auto_start_server`), so `sim serve` is only needed explicitly for remote hosts — and `sim stop` is the counterpart that reaps that background process.

This tiering is load-bearing for docs and error messages: never imply `sim scan` needs a plugin, and never imply `sim check` works without one.

The shared runtime skill is bundled at `src/sim/_skills/sim-cli/` and synced into agent skill directories by `sim plugin sync-skills`. Per-solver agent skills ship inside their own `sim-plugin-<solver>` packages.

## Commands

```bash
# Install
uv pip install -e ".[dev]"          # core + pytest + ruff

# Tests
pytest -q                            # unit tests (no solver needed)
pytest tests/base/test_scan.py       # single test file
pytest -q -m integration             # integration tests (need solvers + sim serve)

# Lint
ruff check src/sim tests
ruff check --fix src/sim tests

# CLI — asset parsing (core only, no plugin/solver needed)
sim --json scan ./historical-cases    # bounded summary, paths redacted
sim --json scan model.mph --full --include-paths
sim --json scan case.inp --format abaqus-inp   # force format for a named file

# CLI — sessions
sim serve --host 0.0.0.0             # start HTTP server (default port 7600)
sim --host <ip> connect --solver <name> --mode solver --ui-mode gui
sim --host <ip> exec "solver.settings.mesh.check()"
sim --host <ip> inspect session.summary
sim --host <ip> screenshot -o shot.png
sim --host <ip> disconnect

sim disconnect                        # tear down the session
sim stop                              # reap the auto-started local server

sim run script.py --solver pybamm    # one-shot mode
sim logs                              # list runs
sim logs last --field voltage_V      # extract a parsed field
sim check <name>                      # solver availability (needs the plugin)
sim lint script.py                    # validate before running (needs the plugin)
sim --json describe                   # machine-readable command manifest
```

**`--json` is a group-level flag and must precede the subcommand.** `sim --json describe` works; `sim describe --json` fails with `Error: No such option: --json`. The same applies to `--host`, `--port`, and `--session`. Note `docs/agent-readability.md` still shows the broken postfix form in two places.

Environment variables: `SIM_HOST`, `SIM_PORT` (CLI client, also `[server]` in config), `SIM_HOME` (global config + history dir, default `~/.sim/`), `SIM_DIR` (project dir, default `./.sim/`).

Config files (issue #5): `~/.sim/config.toml` (global) + `.sim/config.toml` (project). Resolution order `env > project > global > default`. With no config files present, behavior is unchanged from pre-config sim. Run `sim config path | show | init` to manage. See `docs/architecture/multi-session-and-config.md` for the full schema.

## Architecture

### CLI (`src/sim/cli.py`)
Click app with subcommands: `serve`, `scan`, `check`, `lint`, `run`, `connect`, `exec`, `inspect`, `ps`, `disconnect`, `stop`, `screenshot`, `logs`, `config`, `init`, `setup`, `plugin`, `describe`. The session-related commands (`connect`/`exec`/`inspect`/`ps`/`disconnect`/`screenshot`) all delegate to `sim.session.SessionClient`, an HTTP client that talks to a running `sim serve`. The non-session commands (`scan`, `run`, `lint`, `check`, `logs`, `config`, `init`, `setup`, `plugin`, `describe`) work locally without a server.

### Asset parsing (`src/sim/assets.py`)
`sim scan` → `assets.scan_assets(paths, ...)`, which lazily imports the `simparse` native extension (`_load_simparse`) and calls `simparse.scan` / `simparse.inspect`. There is no Python-level parser here: `assets.py` handles path walking, redaction, bounding, and envelope shaping; all format knowledge lives in the compiled `simparse` wheel.

Formats and their `--format` ids come from the `simparse` package metadata — check `simparse-<ver>.dist-info/METADATA` for the authoritative table rather than guessing, and re-check when the pinned range in `pyproject.toml` (`simparse>=0.3.2,<0.4`) moves. As of 0.3.2: COMSOL `.mph` (`comsol-mph`), Abaqus `.inp`/`.inc` (`abaqus-inp`), Fluent `.cas.h5`/`.msh.h5` (`fluent-hdf5`), Ansys Electronics Desktop `.aedt`/`.aedtz` (`hfss-aedt`), Ansys Mechanical `.mechdb`/`.mechdat` (`ansys-mechanical`), Icepak Classic `.tzr` (`icepak-tzr`), Simcenter FloTHERM `.pack`/`.xml`/`.floxml` (`flotherm-pack`, `flotherm-floxml`).

Output contract (`schema_version: "sim.scan/v1"`), which agents depend on:
- **Default (summary) view is bounded** — every list is wrapped as `{total, sample, truncated}` so a large directory scan cannot blow up an agent's context. `--full` returns plain lists and is documented for small input sets only.
- **Absolute paths are redacted** unless `--include-paths` is passed. Preserve this default in any new output path.
- `--format` is honored only for explicitly named files; directory scans always auto-detect.
- Unparseable input yields `error_code: ASSET_FORMAT_UNSUPPORTED` inside the standard failure envelope, not an exception.

### HTTP server (`src/sim/server.py`)
FastAPI app exposing:
- `POST /connect` — launch a solver, register a new session in `_sessions: dict[str, SessionState]` keyed by session_id
- `POST /exec` — `exec()` a Python snippet against the live `session`/`meshing`/`solver` namespace for the session selected by `X-Sim-Session` header (or the single live session if unambiguous); capture stdout/stderr/return value, append to that session's runs
- `GET /inspect/<name>` — query `session.summary`, `session.mode`, `last.result`, `workflow.summary` (session-scoped)
- `POST /run` — one-shot script execution (no session required)
- `GET /ps` — list of all live sessions + default_session (set only when exactly one live)
- `GET /screenshot` — base64 PNG of the server's desktop
- `POST /disconnect` — tear down the session selected by `X-Sim-Session` (or the sole live session)
- `POST /shutdown` — tear down all sessions, exit the server process

The server supports multiple concurrent sessions keyed by session_id. Each `SessionState` carries its own `threading.Lock` so exec/inspect against different sessions can run in parallel. A single solver name can only be live once (driver instances are module-level singletons).

**`sim serve --reload` drops all sessions on any source change under the watched tree.** uvicorn's reload watchdog observes file mtimes in `src/sim/**`; any edit (git pull, scp of a modified driver, even touching an unrelated module) restarts the worker, wiping `_sessions`. Child solver processes (out-of-process GUIs, separately spawned solver binaries) survive the reload because they're spawned separately, but the session handles to them are gone — you have to `connect` again. Driver temp files written into the solver's workspace live outside `src/` so they don't retrigger. Practical rules:

- Don't edit driver code mid-experiment; finish the run, then edit.
- For long autonomous experiments where you're editing driver code iteratively, launch **without** `--reload` and restart manually when you want the new code picked up.
- Reconnecting after a reload can take tens of seconds for GUI-mode drivers that re-adopt the existing window rather than relaunching it.

### Driver protocol (`src/sim/driver.py`)
`DriverProtocol` (a `runtime_checkable` `Protocol`):
- `name: str` — registered driver name
- `detect(script) -> bool` — does this script target this solver?
- `lint(script) -> LintResult` — pre-execution validation, returns `Diagnostic`s
- `connect() -> ConnectionInfo` — package availability + version check
- `parse_output(stdout) -> dict` — extract structured results (convention: last JSON line on stdout)
- `run_file(script) -> RunResult` — one-shot execution

`LintResult`, `Diagnostic`, `RunResult`, `ConnectionInfo` are dataclasses with `to_dict()` for JSON serialization.

### Driver registry (plugin entry points)

`sim-cli-core` is solver-agnostic and ships with no in-tree solver drivers. Drivers are provided by installed plugin packages that expose the `sim.drivers` entry-point group. Use `sim plugin list` and `sim plugin info <name>` to inspect the plugins visible in the active environment.

Plugin implementation work belongs in the owning `sim-plugin-<solver>` repository, where the package metadata, `DriverProtocol` implementation, `compatibility.yaml`, bundled skills, and plugin tests live. Do not add solver drivers under `src/sim/drivers/<name>` in this repo.

A driver may set `supports_session = True` to implement the persistent-session lifecycle (`launch`/`run`/`query`/`disconnect`); the rest are one-shot only. `get_driver(name)` looks up by `.name` attribute and lazily imports the implementation module on first use, so a broken plugin does not crash the CLI.

### Execution pipeline — one-shot (`run`)
1. `cli.run` → `runner.execute_script(script, solver, driver)` → subprocess, captures stdout/stderr/duration
2. `driver.parse_output(stdout)` → extract structured fields
3. `history.append({cwd, solver, session_id, run_id, ...})` → single jsonl line in `~/.sim/history.jsonl`
4. `sim logs <id>` reads back via `history.get_by_id`; `sim logs --solver X --all` filters

### Execution pipeline — persistent session (`exec`)
1. `cli.connect` → HTTP `POST /connect` to server → `driver.launch(...)` → new `SessionState` added to `_sessions`; response carries the session_id which the client stores
2. `cli.exec` → HTTP `POST /exec` with code + `X-Sim-Session: <id>` → server routes to that session, then `_execute_snippet()` runs `exec(code, namespace)` where `namespace` has `session`, `meshing`/`solver`, `_result`
3. `cli.inspect <name>` → HTTP `GET /inspect/<name>` (session-scoped) → driver- or session-specific query
4. `cli.disconnect` → HTTP `POST /disconnect` (session-scoped) → driver-specific teardown, remove from `_sessions`

Session routing rules: an explicit `X-Sim-Session` header wins (404 if unknown); otherwise the server falls back to the sole live session; otherwise `/exec` returns 400. Clients can also set `SIM_SESSION` env var or pass `sim --session <id> ...` to scope a whole CLI invocation.

## Adding or changing a solver driver

Create or update solver drivers in the owning `sim-plugin-<solver>` repository. A plugin should implement `DriverProtocol`, register the driver through `[project.entry-points."sim.drivers"]` in its `pyproject.toml`, and carry its own compatibility metadata, bundled skills, and tests.

The core CLI should only change when the shared runtime contract or plugin discovery machinery changes. Before editing driver-facing docs or behavior, inspect the installed environment with `sim plugin list` and `sim plugin info <solver>`, then work in the plugin repo that owns that solver.

**Prefer generic primitives over task-specific ones.** Before adding a new
driver method purpose-built for one workflow (a resumable-sweep runner, an
auto-coupling helper, etc.), check whether bounded `run(timeout_s=...)` +
`health()`/progress inspection + the solver's own retained state already let
the agent script that workflow step-by-step. Add a new dedicated primitive
only for a genuine generic gap proven by a real session (missing timeout
guard, no orphan-process cleanup, no liveness check) — not for workflow
convenience alone. See `sim-studio-desktop` issues #62/#80 for the HFSS case
this pattern was drawn from.

## Test Layout

```
tests/
  __init__.py
  conftest.py                        shared fixtures / execution paths
  base/                              core framework tests (no solver needed)
    test_scan.py                     asset scanning contract (envelope, bounding, redaction)
    test_cli.py                      smoke tests for click commands
    test_describe.py                 CLI manifest / self-describing surface
    test_compat.py                   skills layering / profile resolution
    test_config.py                   two-tier config resolution
    test_init_setup.py               sim.toml init + setup, exit codes
    test_connect.py                  driver.connect() availability checks
    test_driver_discovery.py         entry-point plugin discovery
    test_plugins.py                  plugin listing / info
    test_plugin_install.py           retired-installer migration shim
    test_protocol_conformance.py     DriverProtocol conformance
    test_history.py                  global run history persistence
    test_lint.py                     lint protocol coverage
    test_lint_public_corpus.py       lint against a public script corpus
    test_logs.py                     sim logs CLI
    test_multi_session.py            session routing + concurrency
    test_session_versions.py         session.versions inspect target
    test_run.py                      one-shot subprocess execution
    test_python_floor_audit.py       minimum-Python-version audit
  drivers/                           per-solver driver checks (skipped without the solver)
  execution/                         end-to-end solver runs (integration marker)
  gui/                               GUI facade + connect tool fields
  inspect/                           inspect targets, probes, snippet timeouts
  fixtures/                          mock scripts and shared test assets
```

Only `-m integration` tests need solvers; `pytest -q` runs green with no plugins installed.

Solver plugin tests live in their own plugin repos. Tests in this repo cover the shared CLI/runtime contract and plugin discovery behavior.

## Notes

- Global run history lives in `~/.sim/history.jsonl` (append-only; override dir via `SIM_HOME`); git-ignored
- The server supports multiple concurrent sessions keyed by `X-Sim-Session` header; a solver name can only be live once per server process (driver instances are module-level singletons)
- Project uses `uv` for dependency locking (`uv.lock`)
- The shared runtime skill lives at `src/sim/_skills/sim-cli/`; per-solver skills ship in their `sim-plugin-<solver>` packages (synced via `sim plugin sync-skills`)

## Releases

- **PyPI distribution name:** `sim-cli-core` (renamed from `sim-runtime` in Phase 4 — see `src/sim/plugins.py` dual-lookup; `sim-runtime 0.2.1`–`0.2.3` remain on PyPI but are no longer released against). Both names were rejected for `sim-cli` itself, which is too similar to the existing `simcli` placeholder.
- **Console script + import name:** `sim`. The PyPI dist name and the import name intentionally differ; `src/sim/__init__.py` looks up `version("sim-cli-core")` first, falling back to `version("sim-runtime")` for editable installs predating the rename, and `try/except PackageNotFoundError` for source checkouts.
- **Trusted publisher:** GitHub OIDC, repo `svd-ai-lab/sim-cli`, workflow `.github/workflows/publish.yml`, environment `pypi`. Configured at https://pypi.org/manage/project/sim-cli-core/settings/publishing/.
- **Tag format:** `v<MAJOR.MINOR.PATCH>` matching `pyproject.toml` `version` exactly. Always tag from `main` after PR-merging a release branch.
- **Don't skip the clean-venv smoke test before tagging.** 0.2.1 shipped broken (`__init__.py` referenced `version("sim-cli")` after the rename) because no one ran `sim --version` in a fresh venv before pushing the tag. Twine check verifies packaging, not import.

## Public-artifact privacy / license safety

When writing anything that lands in a *public* place — GitHub issues,
PR titles/bodies/comments, public commit messages, public docs — keep
**engineering-relevant** facts and drop **diary-style disclosure**
that ties a specific commercial-software install to a specific
machine or account. The two are easy to confuse.

**Keep:**
- The bug, the error message, the exit code, the reproducing input.
- Version info that is a genuine reproduction prereq — when a behavior
  is gated to a specific release of an open-source dependency, the
  version is part of the engineering claim and stays. Use neutral
  framing for closed-source dependencies ("a CFD solver release that
  changed the boundary-condition API") rather than naming the vendor
  and release.
- Platform when behavior is platform-gated (Linux vs Windows
  filesystem casing, COM availability, etc.).

**Drop / replace:**
- Personal usernames and hostnames → "a Windows test host", "a
  development machine", or elide.
- Personal IPs (including Tailscale `100.90.x.x`) → elide.
- Personal filesystem paths (`C:\Users\<you>\...`,
  `~/Documents/GitHub/...`, `C:\Python<NN>\...`,
  `C:\Program Files\<Vendor>\<version>\...`) → "a local clone",
  "the editable install", or elide.
- Specific commercial-software *versions tied to a personal machine*
  — vendor compliance teams treat these as license-audit signals
  even when the version alone would be fine. Replace with neutral
  phrasing.
- Tailscale tailnet names, OS account SIDs, MAC/serial numbers.

Sanitize existing artifacts by editing PR/issue/comment bodies
(`gh pr edit`, `gh issue comment --edit-last`). Avoid force-pushing
to rewrite commit-message history unless the disclosure is severe
*and* the branch is unmerged *and* not being collaborated on.
