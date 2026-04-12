# Development

## Setup

```bash
git clone https://github.com/svd-ai-lab/sim-cli.git
cd sim-cli
uv pip install -e ".[dev]"

pytest -q                       # unit tests (no solver needed)
pytest -q -m integration        # integration tests (need solvers + sim serve)
ruff check src/sim tests
```

## Adding a new driver

Drop a `DriverProtocol` implementation under `src/sim/drivers/<name>/driver.py`, register it in `drivers/__init__.py`, and you're done. See `pybamm/driver.py` for the smallest reference; `fluent/` for a full persistent-session driver.

The server routes all drivers through `DriverProtocol` — no `server.py` changes needed. Set `supports_session = True` for persistent-session drivers, `False` for one-shot only.

## Project layout

```
src/sim/
  cli.py           Click app, all subcommands
  server.py        FastAPI server (sim serve)
  session.py       HTTP client used by connect/exec/inspect
  driver.py        DriverProtocol + result dataclasses
  compat.py        Version-compat profiles + layered skill resolution
  drivers/
    fluent/        Reference: persistent-session driver
                   (driver.py + runtime.py + queries.py)
    pybamm/        Reference: smallest one-shot driver
    flotherm/      GUI automation driver (Win32 + UIA backend)
    …              one folder per registered backend
    __init__.py    DRIVERS registry — register new backends here
tests/             unit tests + fixtures (84 tests)
assets/            logo · banner · architecture (SVG)
docs/              translated READMEs (de · ja · zh) + architecture docs
```

## Dev flags and utilities

### `sim serve --reload`

Auto-restarts the server when source files change. Useful during driver development:

```bash
sim serve --reload
```

### `sim disconnect --stop-server`

Convenience flag that tears down the session *and* stops the server in one call (equivalent to `sim disconnect && sim stop`):

```bash
sim disconnect --stop-server
```

### `SIM_DEV_MODE=1`

Gates dangerous features behind an env var. Currently:

- **Flotherm `#!python` exec** — raw Python execution through the Flotherm driver is blocked unless `SIM_DEV_MODE=1` is set.

## Layered skill composition

Skills in [`sim-skills`](https://github.com/svd-ai-lab/sim-skills) use a layered directory structure to handle SDK and solver version differences:

```
sim-skills/<driver>/
  base/                     shared — always loaded
  sdk/<sdk_version>/        override when SDK API differs
  solver/<solver_version>/  override when solver behavior differs
  SKILL.md                  index
```

Resolution order: `solver → sdk → base` (last-declaring layer wins per file).

Each driver's `compatibility.yaml` declares `active_sdk_layer` and `active_solver_layer` per profile. The server returns these in the `/connect` response so the agent knows which skill layer to use.

Drivers without version-sensitive SDK content omit `sdk/`; drivers without solver-version differences omit `solver/`. The `base/` layer is always present.

Cross-check: `verify_skills_layout(root, profiles)` in `compat.py` validates that every declared layer has a matching on-disk directory.

## Architecture docs

- [`docs/architecture/version-compat.md`](architecture/version-compat.md) — profile env design
- [`docs/architecture/skills-layering-plan.md`](architecture/skills-layering-plan.md) — layered skill composition design
