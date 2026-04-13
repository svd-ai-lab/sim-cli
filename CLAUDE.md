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

Environment variables: `SIM_HOST`, `SIM_PORT` (CLI client), `SIM_DIR` (run history dir, default `.sim/`).

## Architecture

### CLI (`src/sim/cli.py`)
Click app with subcommands: `serve`, `check`, `lint`, `run`, `connect`, `exec`, `inspect`, `ps`, `disconnect`, `screenshot`, `logs`. The session-related commands (`connect`/`exec`/`inspect`/`ps`/`disconnect`/`screenshot`) all delegate to `sim.session.SessionClient`, an HTTP client that talks to a running `sim serve`. The non-session commands (`run`, `lint`, `check`, `logs`) work locally without a server.

### HTTP server (`src/sim/server.py`)
FastAPI app exposing:
- `POST /connect` — launch a solver, hold session in module-level `_state`
- `POST /exec` — `exec()` a Python snippet against the live `session`/`meshing`/`solver` namespace, capture stdout/stderr/return value, append to `_state.runs`
- `GET /inspect/<name>` — query `session.summary`, `session.mode`, `last.result`, `workflow.summary`
- `POST /run` — one-shot script execution (no session required)
- `GET /ps` — current session status
- `GET /screenshot` — base64 PNG of the server's desktop
- `POST /disconnect` — tear down the session

The server keeps a single global `_state: SessionState` (one session per server process).

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

Drivers with `supports_session = True` (fluent, ansa, flotherm, matlab, workbench, mechanical, cfx) implement persistent-session lifecycle (`launch`/`run`/`query`/`disconnect`). The rest are one-shot only.

`get_driver(name)` looks up by `.name` attribute.

### Execution pipeline — one-shot (`run`)
1. `cli.run` → `runner.execute_script(script, solver, driver)` → subprocess, captures stdout/stderr/duration
2. `driver.parse_output(stdout)` → extract structured fields
3. `store.RunStore.save(result, parsed_output)` → write `.sim/runs/NNN.json`, return numeric `run_id`
4. `sim logs <id>` reads back via `RunStore.get`

### Execution pipeline — persistent session (`exec`)
1. `cli.connect` → HTTP `POST /connect` to server → `driver.launch(...)` → `_state.session` populated
2. `cli.exec` → HTTP `POST /exec` with code → server `_execute_snippet()` runs `exec(code, namespace)` where `namespace` has `session`, `meshing`/`solver`, `_result`
3. `cli.inspect <name>` → HTTP `GET /inspect/<name>` → driver- or session-specific query
4. `cli.disconnect` → HTTP `POST /disconnect` → driver-specific teardown, clear `_state`

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

- Run storage lives in `.sim/runs/` (overridable via `SIM_DIR`); git-ignored
- The server holds **one** session at a time (single global `_state`) — multi-tenant is not yet implemented
- Project uses `uv` for dependency locking (`uv.lock`)
- Companion knowledge / skills / workflows live in the sibling `sim-skills/` tree, one folder per solver
