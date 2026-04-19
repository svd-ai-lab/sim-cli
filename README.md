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

LLM agents already know how to write PyFluent, MATLAB, COMSOL, and OpenFOAM scripts — training data is full of them. What they *don't* have is a standard way to **launch a solver, drive it step by step, and observe what happened** before deciding the next move.

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

```bash
# 1. On the box that has the solver (e.g. a Fluent workstation), install
#    sim core only — no SDK choices yet:
uv pip install "git+https://github.com/svd-ai-lab/sim-cli.git"

# 2. Tell sim to look at this machine and pick the right SDK profile:
sim check fluent
# → reports detected Fluent installs and the profile they resolve to

# 3. Bootstrap that profile env (creates .sim/envs/<profile>/ with the
#    pinned SDK; or pass --auto-install to step 4 to do it inline):
sim env install pyfluent_0_38_modern

# 4. Start the server (only needed for remote / cross-machine workflows):
sim serve --host 0.0.0.0          # FastAPI on :7600

# 5. From the agent / your laptop / anywhere on the network:
sim --host <server-ip> connect --solver fluent --mode solver --ui-mode gui
sim --host <server-ip> inspect session.versions   # ← always do this first
sim --host <server-ip> exec "solver.settings.mesh.check()"
sim --host <server-ip> screenshot -o shot.png
sim --host <server-ip> disconnect
```

That's the full loop: **detect → bootstrap → launch → drive → observe → tear down** — with the engineer optionally watching the solver GUI in real time.

> **Why the bootstrap step?** Each (Solver, SDK, driver, skill) combo is its own
> compatibility universe — Fluent 24R1 needs PyFluent 0.37.x; Fluent 25R2 wants
> 0.38.x. sim treats each as an isolated "profile env" so you can have both
> versions on one machine without dependency conflicts. The full design is in
> [`docs/architecture/version-compat.md`](docs/architecture/version-compat.md).

---

## 🧪 Solver registry

The driver registry is **open and intentionally growing** — adding a new backend is a ~200-LOC `DriverProtocol` implementation plus one line in `drivers/__init__.py`. Below is a snapshot of what currently ships in `main`:

| Domain | Example backends shipping today | Sessions | Status |
|---|---|---|---|
| Electronics thermal | Simcenter Flotherm | persistent (GUI) | ✅ Working — model generation from natural language, XSD-validated FloSCRIPT, step-by-step build with checkpoints |
| CFD | Ansys Fluent, OpenFOAM, Simcenter STAR-CCM+, Ansys CFX | persistent / one-shot | ✅ Working |
| Multiphysics | COMSOL Multiphysics | one-shot | ✅ Working |
| CAE | Ansys Workbench, Ansys Mechanical, Abaqus | persistent / one-shot | ✅ Working |
| Explicit FEA | Ansys LS-DYNA | one-shot | ✅ Working |
| Pre-processing | BETA CAE ANSA | persistent / one-shot | ✅ Working (Phase 1) |
| Numerical / scripting | MATLAB | one-shot | ✅ Working (v0) |
| Battery modeling | PyBaMM | one-shot | ✅ Working |
| Implicit FEA | Ansys MAPDL, CalculiX, Elmer FEM, PyMFEM, scikit-fem, SfePy, OpenSeesPy | persistent / one-shot | ✅ Working |
| Pre/post-processing | Gmsh, meshio, pyvista, ParaView, HyperMesh, Trimesh | one-shot | ✅ Working |
| Embodied-AI / GPU physics | NVIDIA Isaac Sim, NVIDIA Newton (Warp) | one-shot | ✅ Working — Newton: Route A recipe JSON + Route B run-script; Isaac: SimulationApp bootstrap + AST lint |
| Open-source CFD | OpenFOAM, SU2 | one-shot / remote | ✅ Working |
| Molecular dynamics | LAMMPS | one-shot | ✅ Working |
| FD codegen / seismic | Devito | one-shot | ✅ Working |
| Thermo properties / combustion | CoolProp, Cantera | one-shot | ✅ Working |
| Optimization / MDAO | OpenMDAO, pymoo, Pyomo | one-shot | ✅ Working |
| Discrete-event simulation | SimPy | one-shot | ✅ Working |
| Power systems / RF | pandapower, scikit-rf | one-shot | ✅ Working |
| **+ your solver** | open a PR — see [Adding a driver](#-development) | — | 🛠 |

Per-solver protocols, snippets, and demo workflows live in [`sim-skills`](https://github.com/svd-ai-lab/sim-skills), which is **also designed to grow** alongside the driver registry — one new agent skill per new backend.

---

## 🎬 Demo

> 📺 **Early preview:** [first walkthrough on YouTube](https://www.youtube.com/watch?v=3Fg6Oph44Ik) — rough cut, a polished recording is still wanted (see below).

> **Recording in progress.** A short terminal capture of `sim connect → exec → inspect → screenshot` against a real Fluent session will land here. The exact sequence to record:
>
> ```bash
> sim serve --host 0.0.0.0
> sim --host <ip> connect --solver fluent --mode solver --ui-mode gui --auto-install
> sim --host <ip> inspect session.versions    # ← step 0: which profile am I in?
> sim --host <ip> exec "solver.settings.file.read_case(file_name='mixing_elbow.cas.h5')"
> sim --host <ip> exec "solver.settings.solution.initialization.hybrid_initialize()"
> sim --host <ip> exec "solver.settings.solution.run_calculation.iterate(iter_count=20)"
> sim --host <ip> inspect session.summary
> sim --host <ip> disconnect
> ```
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
- **One protocol** (`DriverProtocol`) — every driver is ~200 LOC, registered in `drivers/__init__.py`
- **Persistent + one-shot** from the same CLI — no separate client per mode
- **Open registry** — new solvers land continuously; CFD, multiphysics, thermal, pre-processing, battery models all in scope
- **Companion skills** in [`sim-skills`](https://github.com/svd-ai-lab/sim-skills) so an LLM picks up each new backend without prior context

### 🌐 Remote-friendly
- **HTTP/JSON transport** — runs anywhere `httpx` runs
- **Client / server split** — agent on a laptop, solver on an HPC node, GUI on a workstation
- **Tailscale-ready** — designed for cross-network mesh deployments

---

## ⚙️ Commands

| Command | What it does | Analogy |
|---|---|---|
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

- **Pin a specific profile:** `sim connect --solver fluent --profile pyfluent_0_37_legacy`
- **Skip the profile env entirely (legacy / tests):** `sim connect --solver fluent --inline`
- **Power-user single-env install:** `pip install 'sim-cli[fluent-pyfluent-0-38]'` puts the SDK directly into your current venv. Skips `sim env` entirely; OK when you only need one Fluent version on this machine.

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

When the solver lives on a different machine (a Fluent workstation, an HPC login node, a lab box) and you want to drive it from your laptop, a notebook, or an LLM agent — install `sim-cli` on **both** ends and run `sim serve` on the remote.

```bash
# On the solver host (the machine with Fluent / COMSOL / OpenFOAM / ... installed)
ssh user@solver-host
pip install git+https://github.com/svd-ai-lab/sim-cli.git
sim serve --host 0.0.0.0 --port 7600     # bind to all interfaces

# On your local control machine
sim --host <solver-host-ip> connect --solver fluent --mode meshing
sim --host <solver-host-ip> exec "session.settings.mesh.check()"
sim --host <solver-host-ip> inspect session.summary
sim --host <solver-host-ip> disconnect
sim --host <solver-host-ip> stop          # shut down the remote server when done
```

That is the entire setup — same `sim-cli` package on both sides, same wire protocol whether it is talking to a local or a remote server. Bind `--host 0.0.0.0` only on networks you trust (Tailscale, VPN, LAN behind a firewall); there is **no auth layer** on `/connect` and `/exec` execute arbitrary Python.

---

## 🔗 Related projects

- **[`sim-skills`](https://github.com/svd-ai-lab/sim-skills)** — agent skills, snippets, and demo workflows for each supported solver

---

## 📰 News

Highlights from the last few milestones — full history in [`CHANGELOG.md`](CHANGELOG.md).

- **2026-04-19** 🤖 **Isaac Sim + Newton drivers — embodied-AI category** — two new GPU-physics drivers. `isaac`: NVIDIA Isaac Sim 4.5/5.0 (Omniverse Kit) with SimulationApp bootstrap contract, AST-based import-order lint, and `ISAAC_PYTHON`/`ISAAC_VENV` → `sys.executable` interpreter resolution. `newton`: NVIDIA Newton 1.x on Warp, accepting both Route A (declarative recipe JSON, 6 solver backends — XPBD/VBD/MuJoCo/ImplicitMPM/Style3D/SemiImplicit) and Route B (Python run-script with `SIM_ARTIFACT_DIR` collection). 3 canonical Newton E2E: basic_pendulum (XPBD/CPU), robot_g1 (MuJoCo + USD importer + replicate), cable_twist (VBD via `newton.examples`). Subprocess entry launched by file path with flat sibling imports so the newton venv never has to import the shared sim package.
- **2026-04-16** 🔧 **HyperMesh driver** — new Altair HyperMesh FE pre-processor driver. Python `hm` API with 1946 model methods + 225 entity classes. Batch execution via `hw -b -script`. Detects via ALTAIR_HOME env, PATH, Program Files scan. 26 unit tests. 2-profile compat matrix (2024-2025).
- **2026-04-16** 🔬 **ParaView driver** — new Kitware ParaView post-processing driver. Detects `pvpython`/`pvbatch` on PATH, conda `paraview` package, or binary installs in standard locations. One-shot via `pvpython script.py` using `paraview.simple` API. 26 unit tests (detect/lint/connect/parse/run). Supports 30+ input formats (.vtu/.vtk/.case/.foam/.cgns/.pvd/.exo/.stl/.xdmf). 2-profile compat matrix (5.12–5.13).
- **2026-04-16** 🔧 **ICEM CFD driver** — new Ansys ICEM CFD meshing preprocessor driver. Pure CLI Orchestration via `icemcfd.bat -batch -script <file.tcl>` (Tcl 8.4 scripting, 1850 `ic_*` commands). Batch tetra meshing via `ic_run_tetra` (Programmer's Guide p143). 15 unit tests + Box.tin → 26752 tetra E2E (860 KB `.uns`, 3.9s). 4-profile compat matrix (24.1–25.2). No session mode — ICEM is a preprocessor, one-shot is the correct model.
- **2026-04-15** 🐍 **Pure-Python simulation ecosystem — 13 new pip-installable drivers**: OpenSeesPy, SfePy, Cantera, OpenMDAO, FiPy, pymoo, Pyomo, SimPy, Trimesh, Devito, CoolProp, scikit-rf, pandapower. Each verified against analytical/textbook benchmarks (CH4/air adiabatic flame 2225 K, Sellar MDA, NSGA-II ZDT1 Pareto, water T_sat 373.124 K, etc.).
- **2026-04-15** 🐧 **Open-source Linux CAE — 9 new drivers** reachable via remote `sim serve`: CalculiX, Gmsh, SU2, LAMMPS, scikit-fem, Elmer FEM, meshio, pyvista, PyMFEM. Each with Tier-1 unit tests + real-E2E physics verification (cantilever tip 0.1 % err, NACA0012 inviscid, LJ NVT, Poisson < 1 % err).
- **2026-04-14** 🔩 **MAPDL driver (Phase 1 + Phase 2)** — new Ansys MAPDL driver covering both one-shot `sim run` and persistent PyMAPDL gRPC session (`sim connect/exec/inspect`). 4-profile compatibility matrix (24.1–25.2), 2D I-beam + 3D notched plate E2E, same 2D beam re-driven through 10-step session with identical physics.
- **2026-04-14** 🌡 **Flotherm 2410 (2024.3) profile** added to the compatibility matrix.
- **2026-04-14** 🐍 **LS-DYNA session mode + driver-agnostic inspect** — persistent Python namespace with PyDyna `Deck` + DPF `Model`; `sim inspect` no longer hardcodes builtin targets.
- **2026-04-14** 💥 **LS-DYNA driver** — explicit/implicit nonlinear FEA via `.k` keyword files, single hex tension E2E with 7129-cycle normal termination.
- **2026-04-14** 🌀 **CFX driver** — hybrid `cfx5solve` / `cfx5post -line` / `cfx5post -batch` with 27 unit tests + VMFL015 E2E.

---

## 📄 License

Apache-2.0 — see [LICENSE](LICENSE).

### Third-party solver SDKs

`sim-cli` is a thin wrapper/runtime — it does **not** bundle or redistribute any vendor solver or vendor SDK. Each solver backend is reached through a third-party SDK (e.g. `ansys-fluent-core`, `ansys-mapdl-core`, `ansys-workbench-core`, `ansys-mechanical-core`, `ansys-dyna-core`, `ansys-dpf-core`, `mph`, `matlabengine`) that the user installs separately via `sim env install` or as an optional extra.

Users are responsible for obtaining a valid license for each underlying solver and for complying with the license, copyright, and EULA of every third-party SDK they choose to install alongside `sim-cli`. See [`NOTICE`](NOTICE) for the list of optional SDK dependencies and their upstream locations.

### Trademarks

All product, solver, and company names appearing in this repository are used for identification purposes only. Ownership is retained by the respective holders:

- **Ansys®**, **Fluent®**, **Workbench®**, **Mechanical®**, **MAPDL**, **CFX®**, **LS-DYNA®**, **ICEM CFD™**, **DPF** are trademarks or registered trademarks of **ANSYS, Inc.**
- **Abaqus®**, **SIMULIA®** are trademarks of **Dassault Systèmes**.
- **COMSOL Multiphysics®** is a trademark of **COMSOL AB**.
- **MATLAB®** is a registered trademark of **The MathWorks, Inc.**
- **Simcenter™ STAR-CCM+**, **Simcenter Flotherm™** are trademarks of **Siemens Digital Industries Software**.
- **ANSA®** is a trademark of **BETA CAE Systems**.
- **HyperMesh®**, **Altair®** are trademarks of **Altair Engineering, Inc.**
- **ParaView®** is a trademark of **Kitware, Inc.**
- **OpenFOAM®** is a registered trademark of **OpenCFD Ltd.**
- All other solver and product names are trademarks of their respective owners.

`sim-cli` is an independent open-source project and is **not affiliated with, endorsed by, or sponsored by** any of the vendors listed above.
