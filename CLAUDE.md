# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**sim** is a unified CLI + HTTP runtime that lets LLM agents (and engineers) launch, drive, and observe CAD/CAE simulations across multiple solvers through one consistent interface. It is the "container runtime for simulations" — agents talk to `sim`, `sim` talks to solvers.

The runtime supports two execution modes:

- **One-shot** (`sim run script --solver=X`): subprocess execution, result stored as a numbered run, `sim logs` to browse.
- **Persistent session** (`sim serve` + `sim connect/exec/inspect/disconnect`): a long-lived HTTP server holds a live solver session; agents send code snippets and inspect state without restarting the solver.

The companion repo `sim-skills/` contains per-solver agent skills, reference docs, demo workflows, and integration tests that drive this runtime.

## Commands

```bash
# Install
uv pip install -e ".[dev]"          # core + pytest + ruff

# Tests
pytest -q                            # unit tests (no solver needed)
pytest tests/test_lint.py            # single test file
pytest -q -m integration             # integration tests (need solvers + sim serve)

# Lint
ruff check src/sim tests
ruff check --fix src/sim tests

# CLI
sim serve --host 0.0.0.0             # start HTTP server (default port 7600)
sim --host <ip> connect --solver fluent --mode solver --ui-mode gui
sim --host <ip> exec "solver.settings.mesh.check()"
sim --host <ip> inspect session.summary
sim --host <ip> screenshot -o shot.png
sim --host <ip> disconnect

sim run script.py --solver pybamm    # one-shot mode
sim logs                              # list runs
sim logs last --field voltage_V      # extract a parsed field
sim check fluent                      # solver availability
sim lint script.py                    # validate before running
```

Environment variables: `SIM_HOST`, `SIM_PORT` (CLI client, also `[server]` in config), `SIM_HOME` (global config + history dir, default `~/.sim/`), `SIM_DIR` (project dir, default `./.sim/`).

Config files (issue #5): `~/.sim/config.toml` (global) + `.sim/config.toml` (project). Resolution order `env > project > global > default`. With no config files present, behavior is unchanged from pre-config sim. Run `sim config path | show | init` to manage. See `docs/architecture/multi-session-and-config.md` for the full schema.

## Architecture

### CLI (`src/sim/cli.py`)
Click app with subcommands: `serve`, `check`, `lint`, `run`, `connect`, `exec`, `inspect`, `ps`, `disconnect`, `screenshot`, `logs`. The session-related commands (`connect`/`exec`/`inspect`/`ps`/`disconnect`/`screenshot`) all delegate to `sim.session.SessionClient`, an HTTP client that talks to a running `sim serve`. The non-session commands (`run`, `lint`, `check`, `logs`) work locally without a server.

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

**`sim serve --reload` drops all sessions on any source change under the watched tree.** uvicorn's reload watchdog observes file mtimes in `src/sim/**`; any edit (git pull, scp of a modified driver, even touching an unrelated module) restarts the worker, wiping `_sessions`. Child solver processes (Flotherm GUI, Fluent, etc.) survive the reload because they're spawned separately, but the session handles to them are gone — you have to `connect` again. Driver temp files (written to the solver's workspace, e.g. `flouser/_sim_*.xml`) live outside `src/` so they don't retrigger. Practical rules:

- Don't edit driver code mid-experiment; finish the run, then edit.
- For long autonomous experiments where you're editing driver code iteratively, launch **without** `--reload` and restart manually when you want the new code picked up.
- Reconnecting after a reload takes ~20s for GUI-mode Flotherm (the existing GUI process is re-adopted; no re-launch needed).

### Driver protocol (`src/sim/driver.py`)
`DriverProtocol` (a `runtime_checkable` `Protocol`):
- `name: str` — registered driver name
- `detect(script) -> bool` — does this script target this solver?
- `lint(script) -> LintResult` — pre-execution validation, returns `Diagnostic`s
- `connect() -> ConnectionInfo` — package availability + version check
- `parse_output(stdout) -> dict` — extract structured results (convention: last JSON line on stdout)
- `run_file(script) -> RunResult` — one-shot execution

`LintResult`, `Diagnostic`, `RunResult`, `ConnectionInfo` are dataclasses with `to_dict()` for JSON serialization.

### Driver registry (`src/sim/drivers/__init__.py`)
`DRIVERS` — module-level list of instantiated driver objects:

| Name | Class | Layout |
|---|---|---|
| `pybamm` | `PyBaMMLDriver` | `pybamm/driver.py` |
| `fluent` | `PyFluentDriver` | `fluent/driver.py` + `runtime.py` + `queries.py` |
| `matlab` | `MatlabDriver` | `matlab/driver.py` |
| `comsol` | `ComsolDriver` | `comsol/driver.py` |
| `flotherm` | `FlothermDriver` | `flotherm/driver.py` + `_helpers.py` |
| `ansa` | `AnsaDriver` | `ansa/driver.py` + `runtime.py` + `schemas.py` |
| `openfoam` | `OpenFOAMDriver` | `openfoam/driver.py` |
| `workbench` | `WorkbenchDriver` | `workbench/driver.py` + `compatibility.yaml` |
| `mechanical` | `MechanicalDriver` | `mechanical/driver.py` + `compatibility.yaml` |
| `abaqus` | `AbaqusDriver` | `abaqus/driver.py` |
| `starccm` | `StarccmDriver` | `starccm/driver.py` + `compatibility.yaml` |
| `cfx` | `CfxDriver` | `cfx/driver.py` + `compatibility.yaml` |
| `ls_dyna` | `LsDynaDriver` | `lsdyna/driver.py` + `compatibility.yaml` |
| `mapdl` | `MapdlDriver` | `mapdl/driver.py` + `compatibility.yaml` |
| `icem` | `IcemDriver` | `icem/driver.py` + `compatibility.yaml` |
| `paraview` | `ParaViewDriver` | `paraview/driver.py` + `compatibility.yaml` |
| `hypermesh` | `HyperMeshDriver` | `hypermesh/driver.py` + `compatibility.yaml` |

Drivers with `supports_session = True` (fluent, ansa, flotherm, matlab, workbench, mechanical, cfx, ls_dyna, mapdl) implement persistent-session lifecycle (`launch`/`run`/`query`/`disconnect`). The rest are one-shot only.

LS-DYNA is a special case: the *solver* is one-shot (no live process to connect to), but the session holds a persistent Python namespace with PyDyna `Deck`/`run_dyna` and a DPF `Model` so deck-building and post-processing can be driven incrementally via `sim exec`.

`get_driver(name)` looks up by `.name` attribute.

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

## Adding a new driver

1. Create `src/sim/drivers/<name>/driver.py` implementing `DriverProtocol`
2. (Optional) `runtime.py` for persistent-session support
3. Register in `src/sim/drivers/__init__.py`: import and append to `DRIVERS`
4. If the driver needs server-side launch logic, extend `server.py`'s `/connect` handler accordingly

See `pybamm/driver.py` for the smallest reference implementation; `fluent/` for a full persistent-session example.

## Test Layout

```
tests/
  __init__.py
  conftest.py                        shared FIXTURES / EXECUTION paths
  base/                              core framework tests (no solver needed)
    test_cli.py                      smoke tests for click commands
    test_compat.py                   skills layering / profile resolution
    test_connect.py                  driver.connect() availability checks
    test_lint.py                     lint protocol coverage
    test_run.py                      one-shot subprocess execution
    test_store.py                    RunStore persistence
    test_logs.py                     sim logs CLI
  drivers/                           per-driver unit + integration tests
    abaqus/
      test_abaqus_driver.py          protocol compliance
      test_abaqus_e2e.py             cantilever beam E2E
    comsol/
      test_comsol_driver.py          unit tests
    flotherm/
      test_flotherm_lint.py          FloSCRIPT XSD validation
    fluent/
      test_fluent_mixing_elbow.py    mixing_elbow E2E
    matlab/
      test_matlab_driver.py          unit tests
    cfx/
      test_cfx_driver.py             unit tests (27 tests)
      test_cfx_e2e.py                VMFL015 verification E2E
    lsdyna/
      test_lsdyna_driver.py          unit tests (24 tests)
      test_lsdyna_e2e.py             single hex tension E2E
    starccm/
      test_starccm_driver.py         unit tests
    workbench/
      test_workbench_driver.py       unit tests (monkeypatched)
      test_workbench_integration.py  real SDK integration
  fixtures/                          mock solver scripts, organized by solver
    abaqus/                          .py + .inp fixtures
    comsol/                          .py fixtures
    matlab/                          .m fixtures
    pybamm/                          .py fixtures
    cfx/                             .ccl + .def fixtures
    lsdyna/                          .k fixtures
    starccm/                         .java fixtures
    workbench/                       .wbjn + .py fixtures
    mock_solver.py                   shared mock scripts
    mock_fail.py
    not_simulation.py
  execution/                         E2E scripts (per solver, manual runs)
    abaqus/                          cantilever beam scripts
    fluent/                          mixing_elbow snippets + PS1 runners
    mechanical/                      static structural E2E + observation coupling
    starccm/                         smoke test Java macro
    workbench/                       SDK example runners
```

Tests that need a real solver are gated by import-availability flags (e.g. `HAS_PYBAMM`) and skip gracefully when the package is missing.

## Notes

- Global run history lives in `~/.sim/history.jsonl` (append-only; override dir via `SIM_HOME`); git-ignored
- The server supports multiple concurrent sessions keyed by `X-Sim-Session` header; a solver name can only be live once per server process (driver instances are module-level singletons)
- Project uses `uv` for dependency locking (`uv.lock`)
- Companion knowledge / skills / workflows live in the sibling `sim-skills/` tree, one folder per solver

## Releases

- **PyPI distribution name:** `sim-runtime` (not `sim-cli` — that was rejected as too similar to the existing `simcli` placeholder).
- **Console script + import name:** `sim`. The PyPI dist name and the import name intentionally differ; `src/sim/__init__.py` looks up `version("sim-runtime")` (wrapped in `try/except PackageNotFoundError` for source/editable installs).
- **Trusted publisher:** GitHub OIDC, repo `svd-ai-lab/sim-cli`, workflow `.github/workflows/publish.yml`, environment `pypi`. Configured at https://pypi.org/manage/project/sim-runtime/settings/publishing/.
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
- Version info that is a genuine reproduction prereq — *"this bug
  reproduces on MATLAB R2024+ because `addpath` rejects `resources/`
  in that release"*. The version is part of the engineering claim.
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
  — e.g. *"MATLAB R2025b on my Windows host at `C:\Program
  Files\MATLAB\R2025b`"*. Vendor compliance teams use these as
  license-audit signals even when the version alone would be fine.
- Tailscale tailnet names, OS account SIDs, MAC/serial numbers.

Sanitize existing artifacts by editing PR/issue/comment bodies
(`gh pr edit`, `gh issue comment --edit-last`). Avoid force-pushing
to rewrite commit-message history unless the disclosure is severe
*and* the branch is unmerged *and* not being collaborated on.
