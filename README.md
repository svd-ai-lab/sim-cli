# sim

> The physics simulation runtime for AI agents.

**[English](#sim)** | [Deutsch](docs/README.de.md) | [日本語](docs/README.ja.md) | [中文](docs/README.zh.md)

## What it does

LLM agents already know how to write simulation scripts (PyFluent, MATLAB, etc.) from training data. But there's no standard way to **launch, control, and observe** simulations — which matters when they're long, stateful, and expensive.

sim gives AI agents (and engineers) a standard interface to engineering simulations — whether running locally, in Docker, or on cloud/HPC. Like a container runtime standardized how Kubernetes talks to containers, sim standardizes how agents talk to solvers.

## Architecture

```
Any machine                              Any machine (with solver)
┌──────────────┐    HTTP/Tailscale   ┌──────────────────┐
│  sim CLI     │ ─────────────────>  │  sim serve       │
│  (client)    │ <─────────────────  │  (FastAPI)       │
└──────────────┘       JSON          │       │          │
                                     │  ┌────▼────────┐ │
                                     │  │ Solver GUI   │ │
                                     │  │ (optional)   │ │
                                     │  └─────────────┘ │
                                     └──────────────────┘
```

## Quick Start

```bash
# On the machine with Fluent (e.g. win1):
uv pip install "git+https://github.com/svd-ai-lab/sim-cli.git"
sim serve --host 0.0.0.0

# From anywhere on the network:
sim --host 100.90.110.79 connect --solver fluent --mode solver --ui-mode gui
sim --host 100.90.110.79 exec "solver.settings.mesh.check()"
sim --host 100.90.110.79 inspect session.summary
sim --host 100.90.110.79 disconnect
```

## Commands

| Command | What it does | Analogy |
|---|---|---|
| `sim serve` | Start HTTP server, hold solver sessions | `ollama serve` |
| `sim connect` | Launch solver, open session | `docker start` |
| `sim exec` | Run code snippet in live session | `docker exec` |
| `sim inspect` | Query live session state | `docker inspect` |
| `sim ps` | List active sessions | `docker ps` |
| `sim disconnect` | Tear down session | `docker stop` |
| `sim run` | One-shot script execution | `docker run` |
| `sim check` | Verify solver availability | `docker info` |
| `sim lint` | Validate script before running | `ruff check` |
| `sim logs` | Browse run history | `docker logs` |

## Why not just run scripts?

| Traditional (fire-and-forget) | sim (step-by-step control) |
|---|---|
| Write full script, run, hope it works | Connect → execute → observe → decide next step |
| Error at step 2 crashes at step 12 | Each step verified before proceeding |
| Agent can't see solver state | `sim inspect` between every action |
| Restart Fluent on every run | Persistent session across snippets |
| No GUI visibility | Engineer watches GUI while agent drives |

## Supported Solvers

| Solver | Status | Backend |
|---|---|---|
| Ansys Fluent | Working | PyFluent (ansys-fluent-core) |
| PyBaMM | Basic | Direct Python |
| COMSOL | Planned | MPh |
| OpenFOAM | Planned | — |

## Development

```bash
# Install (clone first, then editable install)
git clone https://github.com/svd-ai-lab/sim-cli.git
cd sim-cli
uv pip install -e ".[dev,pyfluent]"

# Run tests
pytest tests/                    # unit tests (no solver needed)
pytest --sim-host=<IP>           # integration tests (needs sim serve + Fluent)

# Lint
ruff check src/sim tests
```

## Project Structure

```
src/sim/
    cli.py              # unified CLI entry point
    server.py           # HTTP server (sim serve)
    session.py          # HTTP client (local or remote)
    drivers/
        fluent/         # Ansys Fluent driver
            driver.py
            tests/
                test_driver.py
                test_integration.py
        pybamm/         # PyBaMM driver
            driver.py
```

## License

Apache-2.0
