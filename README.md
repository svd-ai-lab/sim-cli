# sim

> The container runtime for physics simulations.

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10--3.12-blue.svg)](pyproject.toml)
[![Status](https://img.shields.io/badge/status-alpha-orange.svg)](#supported-solvers)
[![Skills](https://img.shields.io/badge/agent_skills-sim--skills-8A2BE2.svg)](https://github.com/svd-ai-lab/sim-skills)

**English** | [Deutsch](docs/README.de.md) | [日本語](docs/README.ja.md) | [中文](docs/README.zh.md)

---

LLM agents already know how to write PyFluent, MATLAB, COMSOL, and OpenFOAM scripts — training data is full of them. What they *don't* have is a standard way to **launch a solver, drive it step by step, and observe what happened** before deciding the next move. `sim` is that missing layer: one CLI, one HTTP protocol, seven solver backends, persistent sessions you can introspect between every action.

## Architecture

```
   Agent / engineer                       Workstation with the solver
  ┌──────────────────┐    HTTP / JSON    ┌──────────────────────────┐
  │   sim CLI        │ ───────────────►  │   sim serve  (FastAPI)   │
  │   (any host)     │ ◄───────────────  │            │             │
  └──────────────────┘                   │   ┌────────▼─────────┐   │
         ▲                               │   │  Live solver     │   │
         │  one-shot mode                │   │  Fluent / COMSOL │   │
         │  (sim run)                    │   │  MATLAB / ANSA   │   │
         └───────────────────────────────┤   │  Flotherm /      │   │
                                         │   │  OpenFOAM /      │   │
                                         │   │  PyBaMM          │   │
                                         │   └──────────────────┘   │
                                         └──────────────────────────┘
```

Two execution modes from the same CLI:

| Mode | Command | When to use it |
|---|---|---|
| **Persistent session** | `sim serve` + `sim connect/exec/inspect` | Long, stateful workflows the agent inspects between steps |
| **One-shot** | `sim run script.py --solver X` | Whole-script jobs you want stored as a numbered run |

## Quick Start

```bash
# On the box that has the solver (e.g. a Fluent workstation):
uv pip install "git+https://github.com/svd-ai-lab/sim-cli.git"
sim serve --host 0.0.0.0

# From the agent / your laptop / anywhere on the network:
sim --host <server-ip> connect --solver fluent --mode solver --ui-mode gui
sim --host <server-ip> exec "solver.settings.mesh.check()"
sim --host <server-ip> inspect session.summary
sim --host <server-ip> disconnect
```

That's the full loop: launch, drive, observe, tear down — with the engineer optionally watching the solver GUI in real time.

## What you get

- **Seven solver drivers** behind one protocol — Fluent, COMSOL, MATLAB, OpenFOAM, ANSA, Flotherm, PyBaMM
- **Persistent sessions** that survive across snippets, so an agent never restarts the solver mid-task
- **Step-by-step introspection** — `sim inspect` between actions instead of fire-and-forget scripts
- **Pre-flight `lint`** that catches missing imports and unsupported APIs before launch
- **Numbered run history** in `.sim/runs/` for one-shot jobs, browsable via `sim logs`
- **Remote-by-default** — the CLI client and the server can live on different machines (LAN, Tailscale, or HPC head node)
- **Companion agent skills** in [`sim-skills`](https://github.com/svd-ai-lab/sim-skills) so an LLM knows how to drive each solver

## Commands

| Command | What it does | Analogy |
|---|---|---|
| `sim serve` | Start the HTTP server, hold one solver session | `ollama serve` |
| `sim connect` | Launch a solver, open a session | `docker start` |
| `sim exec` | Run a Python snippet inside the live session | `docker exec` |
| `sim inspect` | Query live session state | `docker inspect` |
| `sim ps` | Show the active session | `docker ps` |
| `sim screenshot` | Grab a PNG of the solver GUI | — |
| `sim disconnect` | Tear down the session | `docker stop` |
| `sim run` | One-shot script execution | `docker run` |
| `sim check` | Verify a solver / driver is installed | `docker info` |
| `sim lint` | Pre-flight static check on a script | `ruff check` |
| `sim logs` | Browse stored run history | `docker logs` |

Environment: `SIM_HOST`, `SIM_PORT` for the client; `SIM_DIR` (default `.sim/`) for run storage.

## Why not just run scripts?

| Fire-and-forget script | sim |
|---|---|
| Write the whole thing, run, hope it converges | Connect → execute → observe → decide next step |
| An error at step 2 surfaces at step 12 | Each step verified before the next is sent |
| Agent has no view of solver state | `sim inspect` between every action |
| Solver restarts on every iteration | One persistent session, snippets at will |
| GUI invisible to the human | Engineer watches the GUI while the agent drives |

## Supported Solvers

| Solver | Driver | Sessions | Status |
|---|---|---|---|
| Ansys Fluent | `fluent` (PyFluent) | persistent + one-shot | Working |
| BETA CAE ANSA | `ansa` | persistent + one-shot | Working (Phase 1, batch) |
| COMSOL Multiphysics | `comsol` (JPype) | one-shot | Working |
| Simcenter Flotherm | `flotherm` (Win32 / FloSCRIPT) | one-shot | Working (Phase A) |
| MATLAB | `matlab` (matlabengine) | one-shot | Working (v0) |
| OpenFOAM | `openfoam` | one-shot | Working (via `sim serve` on Linux) |
| PyBaMM | `pybamm` | one-shot | Working |

Per-solver protocols, snippets, and demo workflows live in [`sim-skills`](https://github.com/svd-ai-lab/sim-skills).

## Development

```bash
git clone https://github.com/svd-ai-lab/sim-cli.git
cd sim-cli
uv pip install -e ".[dev]"

pytest -q                       # unit tests (no solver needed)
pytest -q -m integration        # integration tests (need solvers + sim serve)
ruff check src/sim tests
```

For deeper architectural notes — driver protocol, server endpoints, execution pipeline — see [CLAUDE.md](CLAUDE.md).

## Project layout

```
src/sim/
  cli.py           # Click app, all subcommands
  server.py        # FastAPI server (sim serve)
  session.py       # HTTP client used by connect/exec/inspect
  driver.py        # DriverProtocol + dataclasses
  drivers/
    fluent/        # PyFluent driver  (driver.py + runtime.py + queries.py)
    ansa/          # ANSA driver      (driver.py + runtime.py + schemas.py)
    comsol/        # COMSOL driver
    flotherm/      # Flotherm driver
    matlab/        # MATLAB driver
    openfoam/      # OpenFOAM driver
    pybamm/        # PyBaMM driver
tests/             # unit tests + fixtures + execution snippets
```

## Related projects

- [`sim-skills`](https://github.com/svd-ai-lab/sim-skills) — agent skills, snippets, and demo workflows for each supported solver

## License

Apache-2.0 — see [LICENSE](LICENSE).
