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

Every driver ships as its own `sim-plugin-<name>` package — sim-cli core has no built-in drivers. Implement `DriverProtocol` in your plugin package, register it via the `sim.drivers` entry-point group in your `pyproject.toml`:

```toml
[project.entry-points."sim.drivers"]
<name> = "sim_plugin_<name>.driver:MyDriver"
```

Set `supports_session = True` for persistent-session drivers, `False` for one-shot only. The server routes all drivers through `DriverProtocol` — no `server.py` changes needed.

Read [`sim-plugin-ltspice`](https://github.com/svd-ai-lab/sim-plugin-ltspice) for shape: driver implementation + skill packaged together.

## Project layout

```
src/sim/
  cli.py             Click app, all subcommands
  server.py          FastAPI server (sim serve)
  session.py         HTTP client used by connect/exec/inspect
  driver.py          DriverProtocol + result dataclasses
  compat.py          Version-compat profiles + layered skill resolution
  plugins.py         Plugin discovery, listing, info
  _plugin_install.py Install / uninstall / index resolution
  drivers/
    __init__.py      Plugin registry — discovers external plugins
                     via the `sim.drivers` entry-point group at
                     import time
tests/               unit tests + fixtures
assets/              logo · banner · architecture (SVG)
docs/                translated READMEs (de · ja · zh) + architecture docs
```

## Dev flags and utilities

### `sim serve --reload`

Auto-restarts the server when source files change. Useful during driver development:

```bash
sim serve --reload
```

On Windows, prefer the module-execution form when you also need to run
`uv sync` mid-iteration:

```bash
python -m sim serve --reload
```

Both invocations reach the same Click group. The difference is only the
running process's open file: `sim serve` holds `.venv\Scripts\sim.exe`,
whereas `python -m sim serve` holds `.venv\Scripts\python.exe`. `uv sync`
re-prepares the editable install on every sync, which means rewriting
`Scripts/sim.exe`; on Windows that fails with `os error 32` if `sim.exe`
is open as a process, and the entire sync aborts. Launching via
`python -m sim` keeps `sim.exe` free, so `uv sync` can complete in-place
while `--reload` continues to pick up source changes. End-user PyPI
workflows aren't affected — they install `sim-cli-core` as a regular wheel
and never re-prepare the editable.

### `sim disconnect --stop-server`

Convenience flag that tears down the session *and* stops the server in one call (equivalent to `sim disconnect && sim stop`):

```bash
sim disconnect --stop-server
```

### `SIM_DEV_MODE=1`

Gates dangerous features behind an env var. Plugins use this to gate
raw-Python escape hatches inside script formats that would otherwise be
declarative-only — without `SIM_DEV_MODE=1`, those code paths refuse to
execute even when the directive is present in the input file.

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
