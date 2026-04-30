<div align="center">

<img src="assets/banner.svg" alt="sim — the container runtime for physics simulations" width="820">

<br>

**Make every engineering tool agent-native.**

*Today's CAD and CAE software was built for engineers clicking through GUIs.*
*Tomorrow's user is an LLM agent — and it needs a way in.*

<p align="center">
  <a href="#-quick-start"><img src="https://img.shields.io/badge/Quick_Start-2_min-3b82f6?style=for-the-badge" alt="Quick Start"></a>
  <a href="#-solver-registry"><img src="https://img.shields.io/badge/Solvers-growing_registry-22c55e?style=for-the-badge" alt="Growing solver registry"></a>
  <a href="https://github.com/svd-ai-lab/sim-skills"><img src="https://img.shields.io/badge/Agent_Skills-sim--skills-8b5cf6?style=for-the-badge" alt="Companion skills"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-eab308?style=for-the-badge" alt="License"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10--3.12-3776AB?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/CLI-Click_8-blue" alt="Click">
  <img src="https://img.shields.io/badge/server-FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/transport-HTTP%2FJSON-orange" alt="HTTP/JSON">
  <img src="https://img.shields.io/badge/status-alpha-f97316" alt="Status: alpha">
</p>

**English** · [Deutsch](docs/README.de.md) · [日本語](docs/README.ja.md) · [中文](docs/README.zh.md)

[Why sim](#-why-sim) · [Quick Start](#-quick-start) · [Solvers](#-solver-registry) · [Commands](#-commands) · [Demo](#-demo) · [Skills](https://github.com/svd-ai-lab/sim-skills)

</div>

---

## 🤔 Why sim?

LLM agents already know how to write simulation scripts — training data is full of them. What they *don't* have is a standard way to **launch a solver, drive it step by step, and observe what happened** before deciding the next move.

Today, the choices are awful:

- **Fire-and-forget scripts** — agent writes 200 lines, runs the whole thing, an error at line 30 surfaces as garbage at line 200, no introspection, no recovery.
- **Bespoke wrappers per solver** — every team rebuilds the same launch / exec / inspect / teardown loop in a different shape.
- **Closed proprietary glue** — vendor SDKs that don't compose, don't share a vocabulary, and don't speak HTTP.

`sim` is the missing layer:

- **One CLI**, one HTTP protocol, **a growing driver registry** spanning CFD, multiphysics, thermal, pre-processing, and beyond.
- **Persistent sessions** the agent introspects between every step.
- **Remote-by-default** — the CLI client and the live solver can sit on different machines (LAN, Tailscale, HPC head node).
- **Companion agent skills** that teach an LLM how to drive each backend safely.

> Like a container runtime standardized how Kubernetes talks to containers, **sim** standardizes how agents talk to solvers.

---

## 🏛 Architecture

<div align="center">
  <img src="assets/architecture.svg" alt="sim architecture: CLI client over HTTP/JSON to a sim serve FastAPI process holding a live solver session" width="900">
</div>

Two execution modes from the same CLI, sharing the same `DriverProtocol`:

| Mode | Command | When to use it |
|---|---|---|
| **Persistent session** | `sim serve` + `sim connect / exec / inspect` | Long, stateful workflows the agent inspects between steps |
| **One-shot** | `sim run script.py --solver X` | Whole-script jobs you want stored as a numbered run in `.sim/runs/` |

For the full driver protocol, server endpoints, and execution pipeline see [CLAUDE.md](CLAUDE.md).

---

## 🚀 Quick Start

> **Names at a glance:** repo `svd-ai-lab/sim-cli` · PyPI distribution `sim-cli-core` · console command `sim` · import `import sim`. Yes, three different strings — the repo name predates the PyPI publish; the rest follow Python packaging convention.
>
> **Agent-assisted Windows install:** Hand [`agent-skills/install-sim-windows/SKILL.md`](agent-skills/install-sim-windows/SKILL.md) to your coding agent, or use [`agent-skills/install-sim-windows-cn/SKILL.md`](agent-skills/install-sim-windows-cn/SKILL.md) for China/restricted networks. Each is a one-page setup guide for `uv`, `sim-cli-core`, and optional commercial plugin wheelhouse install.

```bash
# 1. On the host that has the solver installed, install sim core only
#    — no driver choice yet:
uv pip install sim-cli-core

# 2. Install the plugin for the solver you actually want (browse the
#    index with `sim plugin list`):
sim plugin install <solver>     # e.g. ltspice, coolprop, pybamm

# 3. Tell sim to look at this machine and pick the right SDK profile:
sim check <solver>
# → reports detected installs of <solver> and the profile they resolve to

# 4. Bootstrap that profile env (creates .sim/envs/<profile>/ with the
#    pinned SDK; or pass --auto-install to step 5 to do it inline):
sim env install <profile>

# 5. Start the server (only needed for remote / cross-machine workflows):
sim serve --host 0.0.0.0          # FastAPI on :7600

# 6. From the agent / your laptop / anywhere on the network:
sim --host <server-ip> connect --solver <solver> --mode solver --ui-mode gui
sim --host <server-ip> inspect session.versions   # ← always do this first
sim --host <server-ip> exec "<solver-specific snippet>"
sim --host <server-ip> screenshot -o shot.png
sim --host <server-ip> disconnect
```

That's the full loop: **detect → bootstrap → launch → drive → observe → tear down** — with the engineer optionally watching the solver GUI in real time.

> **Why the bootstrap step?** Each `(solver, SDK, driver, skill)` combo is
> its own compatibility universe — different solver releases may want
> different SDK versions, and those SDK versions can't always coexist in
> one Python env. sim treats each combo as an isolated "profile env" so
> you can keep multiple versions on one machine without dependency
> conflicts. The contract is in
> [`docs/architecture/version-compat.md`](docs/architecture/version-compat.md).

---

## 🧪 Solver registry

`sim-cli` core is **fully solver-agnostic** — it ships with **zero built-in drivers**. Every solver, including OpenFOAM, is reached through an **out-of-tree plugin package** registered via the `sim.drivers` entry-point group. Adding a new backend is a ~200-LOC `DriverProtocol` implementation in its own `sim-plugin-<name>` repo.

Plugin coverage spans CFD, multiphysics, electronics thermal, implicit and explicit structural FEA, pre/post-processing, mesh generation, embodied-AI / GPU physics, molecular dynamics, optimization / MDAO, battery modeling, thermo properties, power-systems and RF simulation, and discrete-event modeling. Browse the curated index:

```bash
sim plugin list                  # what the curated index advertises
sim plugin install <name>        # e.g. sim plugin install ltspice
```

The index is served from [`sim-plugin-index`](https://github.com/svd-ai-lab/sim-plugin-index); reference plugins to read for shape: [`sim-plugin-coolprop`](https://github.com/svd-ai-lab/sim-plugin-coolprop) (one-shot, no SDK gate), [`sim-plugin-ltspice`](https://github.com/svd-ai-lab/sim-plugin-ltspice) (one-shot with vendor binary), [`sim-plugin-pybamm`](https://github.com/svd-ai-lab/sim-plugin-pybamm) (heavy SDK).

**Private plugins** (vendor-IP-sensitive backends not in the public index) install directly by URL — same `sim plugin install` flow:

```bash
sim plugin install git+https://github.com/<org>/sim-plugin-<name>
# (you need read-access to the repo; without it, git clone returns 401)
```

Per-solver protocols, snippets, and demo workflows live in [`sim-skills`](https://github.com/svd-ai-lab/sim-skills) and the per-plugin repos.

---

## 🎬 Demo

> 📺 **Early preview:** [first walkthrough on YouTube](https://www.youtube.com/watch?v=3Fg6Oph44Ik) — rough cut, a polished recording is still wanted (see below).

> **Recording in progress.** A short terminal capture of `sim connect → exec → inspect → screenshot` against a live solver session will land here.
>
> Want to contribute the recording? Use [`vhs`](https://github.com/charmbracelet/vhs) or [`asciinema`](https://asciinema.org/) and open a PR against `assets/demo.gif`.

---

## ✨ Features

### 🧠 Built for agents
- **Persistent sessions** that survive across snippets — never restart the solver mid-task
- **Step-by-step introspection** with `sim inspect` between every action
- **Pre-flight `sim lint`** catches missing imports and unsupported APIs before launch
- **Numbered run history** in `.sim/runs/` for one-shot jobs, browsable via `sim logs`

### 🔌 Solver-agnostic
- **One protocol** (`DriverProtocol`) — every driver is ~200 LOC, shipped as its own `sim-plugin-<name>` package via Python entry points
- **Persistent + one-shot** from the same CLI — no separate client per mode
- **Open plugin index** — discoverable via `sim plugin list`; curated registry at [`sim-plugin-index`](https://github.com/svd-ai-lab/sim-plugin-index)
- **Companion skills** in [`sim-skills`](https://github.com/svd-ai-lab/sim-skills) so an LLM picks up each new backend without prior context

### 🌐 Remote-friendly
- **HTTP/JSON transport** — runs anywhere `httpx` runs
- **Client / server split** — agent on a laptop, solver on an HPC node, GUI on a workstation
- **Tailscale-ready** — designed for cross-network mesh deployments

---

## ⚙️ Commands

| Command | What it does | Analogy |
|---|---|---|
| `sim plugin list / install / uninstall` | Manage out-of-tree solver plugins from the curated index | `npm install` |
| `sim check <solver>` | Detect installations + resolve a profile | `docker info` |
| `sim env install <profile>` | Bootstrap a profile env (venv + pinned SDK) | `pyenv install` |
| `sim env list [--catalogue]` | Show bootstrapped envs (and the full catalogue) | `pyenv versions` |
| `sim env remove <profile>` | Tear down a profile env | `pyenv uninstall` |
| `sim serve` | Start the HTTP server (for cross-machine use) | `ollama serve` |
| `sim connect` | Launch a solver, open a session | `docker start` |
| `sim exec` | Run a Python snippet inside the live session | `docker exec` |
| `sim inspect` | Query live session state (incl. `session.versions`) | `docker inspect` |
| `sim ps` | Show the active session and its profile | `docker ps` |
| `sim screenshot` | Grab a PNG of the solver GUI | — |
| `sim disconnect` | Tear down the session | `docker stop` |
| `sim stop` | Stop the sim-server process | `docker rm -f` |
| `sim run` | One-shot script execution | `docker run` |
| `sim lint` | Pre-flight static check on a script | `ruff check` |
| `sim logs` | Browse stored run history | `docker logs` |

Every command that touches a host (`check`, `env`, `connect`, `exec`, `inspect`, `disconnect`) accepts `--host <ip>` and runs against a remote `sim serve` instead of the local machine.

Environment: `SIM_HOST`, `SIM_PORT` for the client; `SIM_DIR` (default `.sim/`) for run storage and profile envs.

### Choosing a profile

You don't usually have to. `sim check <solver>` tells you which profile your installed solver maps to, and `sim connect ... --auto-install` will bootstrap it for you on first use. The escape hatches:

- **Pin a specific profile:** `sim connect --solver <solver> --profile <profile>`
- **Skip the profile env entirely (legacy / tests):** `sim connect --solver <solver> --inline`
- **Power-user single-env install:** install the matching plugin package directly into your current venv (e.g. `pip install <plugin-package>`). Skips `sim env` entirely; OK when you only need one solver version on this machine.

The full design is in [`docs/architecture/version-compat.md`](docs/architecture/version-compat.md).

---

## 🆚 Why not just run scripts?

| Fire-and-forget script | sim |
|---|---|
| Write the whole thing, run, hope it converges | Connect → execute → observe → decide next step |
| An error at step 2 surfaces at step 12 | Each step verified before the next is sent |
| Agent has no view of solver state | `sim inspect` between every action |
| Solver restarts on every iteration | One persistent session, snippets at will |
| GUI invisible to the human | Engineer watches the GUI while the agent drives |
| Output parsing reinvented per project | `driver.parse_output()` returns structured fields |

---

## 🛠 Development

See [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) for setup, project layout, adding drivers, dev flags, and the layered skill system.

---

## 🌐 Remote deployment

When the solver lives on a different machine (an HPC login node, a lab box, or any host with the solver installed) and you want to drive it from your laptop, a notebook, or an LLM agent — install `sim-cli-core` on **both** ends and run `sim serve` on the remote.

```bash
# On the solver host (the machine with the solver installed)
ssh user@solver-host
pip install sim-cli-core
sim serve --host 0.0.0.0 --port 7600     # bind to all interfaces

# On your local control machine
sim --host <solver-host-ip> connect --solver <solver> --mode <mode>
sim --host <solver-host-ip> exec "<solver-specific snippet>"
sim --host <solver-host-ip> inspect session.summary
sim --host <solver-host-ip> disconnect
sim --host <solver-host-ip> stop          # shut down the remote server when done
```

That is the entire setup — same `sim-cli-core` package on both sides, same wire protocol whether it is talking to a local or a remote server. Bind `--host 0.0.0.0` only on networks you trust (Tailscale, VPN, LAN behind a firewall); there is **no auth layer** on `/connect` and `/exec` execute arbitrary Python.

---

## 🔗 Related projects

- **[`sim-plugin-index`](https://github.com/svd-ai-lab/sim-plugin-index)** — curated registry of out-of-tree solver plugins; what `sim plugin list / install` reads
- **[`sim-skills`](https://github.com/svd-ai-lab/sim-skills)** — agent skills, snippets, and demo workflows for each supported solver
- **[`sim-ltspice`](https://github.com/svd-ai-lab/sim-ltspice)** — standalone Python API for LTspice file formats (used by `sim-plugin-ltspice`)

---

## 📄 License

Apache-2.0 — see [LICENSE](LICENSE).

### Third-party solver SDKs

`sim-cli` is a thin wrapper/runtime — it does **not** bundle or redistribute any vendor solver or vendor SDK. Each solver backend is reached through a third-party SDK that the user installs separately via `sim env install` or as an optional extra.

Users are responsible for obtaining a valid license for each underlying solver and for complying with the license, copyright, and EULA of every third-party SDK they choose to install alongside `sim-cli`. See [`NOTICE`](NOTICE) for the list of optional SDK dependencies and their upstream locations.

### Trademarks

`sim-cli` is an independent open-source project and is **not affiliated with, endorsed by, or sponsored by** any solver vendor. Product, solver, and company names referenced anywhere in this repository remain the property of their respective owners:

- **OpenFOAM®** is a registered trademark of **OpenCFD Ltd.**
- **ParaView®** is a trademark of **Kitware, Inc.**
- All other solver and product names are trademarks of their respective owners.
