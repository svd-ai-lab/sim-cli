# Version Compatibility & Environment Bootstrapping

> **Status:** design accepted, M1 in progress
> **Audience:** sim-cli maintainers, sim-skills maintainers, new driver authors
> **Last reviewed:** 2026-04-08

This document defines how `sim-cli` handles the fact that **every supported solver has its own version sprawl**, each with its own SDK that pins to a narrow window of solver versions, with skill content that is implicitly tied to a specific SDK API surface. It is the contract for the M1 work and the mental model every new driver author must follow.

If you only read one section, read **§3 (Three first-principles axioms)** and **§4 (The detect-then-bootstrap model)**.

---

## 1. The problem, in one paragraph

Ansys Fluent has multiple versions in active use (24.1, 24.2, 25.1, 25.2, …). The Python binding `ansys-fluent-core` (PyFluent) advances on its own schedule and each PyFluent release supports a *window* of Fluent versions — for example, PyFluent 0.38 dropped Fluent 24.1 entirely; PyFluent 0.37 has a different API surface than 0.38 for boundary conditions and cell zones. The driver code in `sim-cli` calls into PyFluent. The skill content in `sim-skills` (snippets, workflows, reference) implicitly assumes a specific PyFluent API. **Four different things need to line up before a single `sim exec` call can succeed**, and right now we encode none of those constraints anywhere — we just pin one SDK version in `pyproject.toml` and hope.

This is the same shape of problem as: browser feature detection, database client/server compatibility, Kubernetes version skew, Linux distro packaging, PyTorch CUDA wheels, dbt adapters, Airflow providers. None of those projects solve it with a single dependency pin. Neither can we.

---

## 2. The four version axes

```
            ┌───────────────────────────────────────────┐
            │         The compatibility surface         │
            └───────────────────────────────────────────┘
              ▲          ▲              ▲           ▲
              │          │              │           │
       (1) Solver   (2) SDK /      (3) Driver  (4) Skill
           version       bindings        code        content
                       (PyFluent,     (sim-cli/   (sim-skills/
                        JPype,         drivers/    fluent/...)
                        matlab-       fluent/)
                        engine, ...)
```

| Axis | Owner | Cadence | Typical drift |
|---|---|---|---|
| (1) Solver binary | The user's IT / license server | yearly | 24.1, 24.2, 25.1, 25.2 |
| (2) SDK / language binding | Vendor or OSS upstream | monthly | PyFluent 0.36 → 0.37 → 0.38 |
| (3) Driver code (`sim-cli/drivers/<solver>/`) | Us | weekly | API call shape changes per profile |
| (4) Skill content (`sim-skills/<solver>/`) | Us | weekly | Snippets pinned to a specific API surface |

These four axes constrain each other in **non-obvious** ways. Selecting Fluent 24.1 forbids PyFluent 0.38; selecting PyFluent 0.38 forces a different driver code path; that driver code path forces different snippet bodies. One choice cascades.

---

## 3. Three first-principles axioms

The whole design follows from these three.

> **Axiom A — Compatibility is data, not prose.**
> The relationships between (solver, SDK, driver, skill) versions must live in a single machine-readable file per driver, consumed identically by sim-cli code, by CI, by users, and by LLM agents. Documentation drifts; data does not.

> **Axiom B — Detection happens at runtime, on demand, against the real environment.**
> sim never assumes it knows the user's solver version. It detects when the user asks. Detection is per-solver and per-host (local or remote), never global "scan everything." This is the LLM equivalent of `caniuse` — feature detection, not design-time guessing.

> **Axiom C — Each (solver, SDK) profile lives in an isolated environment, dispatched by the core process.**
> The core `sim` process holds no SDK dependency. Each profile gets its own venv under `.sim/envs/`. The core spawns a subprocess into the right env when it needs to talk to a solver. Multi-version machines (Fluent 24R2 + 25R2 side by side) work natively; CI matrices fall out for free.

Everything below is mechanism in service of these three axioms.

---

## 4. The detect-then-bootstrap model

The user's experience reduces to **three actions, all of them per-solver and lazy**:

```
                ┌────────────────────────┐
                │  uv tool install sim-cli  (~10 MB, no SDKs)
                └────────────┬───────────┘
                             │
                             ▼
        ┌──────────────────────────────────────────┐
        │  sim check fluent       (or any solver)  │
        │   ─ scans THIS host for fluent installs  │
        │   ─ resolves each to a profile           │
        │   ─ reports + tells you what to bootstrap│
        └────────────┬─────────────────────────────┘
                     │
                     ▼
        ┌──────────────────────────────────────────┐
        │  sim env install fluent-pyfluent-0-38    │
        │   ─ uv venv .sim/envs/fluent-0-38/       │
        │   ─ uv pip install ansys-fluent-core...  │
        │   ─ installs the driver runner shim      │
        └────────────┬─────────────────────────────┘
                     │
                     ▼
        ┌──────────────────────────────────────────┐
        │  sim connect --solver fluent             │
        │   ─ picks env by detected version        │
        │   ─ spawns runner subprocess in that env │
        │   ─ ready                                │
        └──────────────────────────────────────────┘
```

Two non-obvious commitments:

- **`sim init` is NOT a global scanner.** There is no "scan all 7 drivers at once" command. The user always names a solver. Reasoning: detection has cost (registry hits, file walks, env probes); we don't pay that cost for tools the user isn't using; we don't want to confuse a Fluent user by listing the fact that they don't have COMSOL installed.
- **Bootstrap is opt-in.** `sim check fluent` does NOT install anything. It reports. The actual env creation is `sim env install`. We ask before downloading 200 MB of SDK wheels.

The single optional convenience subcommand `sim env install --auto-from-check` lets a confident user do detect+bootstrap in one shot for a named solver, but it still scopes to that one solver.

---

## 5. Two detection modes: local and remote

Detection runs **wherever the solver license and binaries actually live**. There are two cases:

### 5.1 Local detection

```
[user laptop with sim-cli + license + solver installed]
   $ sim check fluent
   → driver.detect_installed() runs in the local sim process
```

Used when the user is on the workstation that has the solver.

### 5.2 Remote detection (via `sim serve`)

```
[Mac]                                   [Windows workstation with Fluent]
$ sim --host 100.90.110.79 check fluent ─────► sim serve (already running)
                                                 │
                                                 ▼
                                              GET /detect/fluent
                                                 │
                                                 ▼
                                       driver.detect_installed()
                                       runs INSIDE the server process
                                                 │
                                                 ▼
                                       returns a JSON list of installs
       ◄─────────────────────────────  back over HTTP
   prints the same install table
```

The remote case is the **important** one for sim's "agent on a Mac, solver on a license server" use case. The remote endpoint runs **the same Python `detect_installed()` code** the local case runs — it just runs it on a different host. There is no second copy of the detection logic.

**Implication for the driver protocol:** `detect_installed()` must be a pure Python method that depends only on stdlib + the driver's own helpers. It must NOT need the SDK to be installed (that is the whole point — we are detecting the *solver*, before we know which SDK to install).

### 5.3 Bootstrap also goes through the right host

```
$ sim --host 100.90.110.79 env install fluent-pyfluent-0-38
       │
       ▼
   POST /env/install
       │
       ▼
   sim serve creates .sim/envs/fluent-0-38/ ON THE WINDOWS BOX,
   not on the user's Mac
```

This is required because the SDK needs to live next to the solver binary — installing PyFluent on a Mac when Fluent runs on Windows is meaningless. The same `--host` flag that controls `connect` and `exec` also controls `check` and `env`.

---

## 6. The `compatibility.yaml` schema

One file per driver, at `sim-cli/src/sim/drivers/<solver>/compatibility.yaml`. This is the single source of truth.

```yaml
# sim-cli/src/sim/drivers/fluent/compatibility.yaml
driver: fluent
sdk_package: ansys-fluent-core

# Each profile is a (solver-version-range, SDK-version-range) named tuple
# that the driver code, the skill, and the CI matrix all agree on.
profiles:

  - name: pyfluent_0_38_modern
    sdk: ">=0.38,<0.39"
    solver_versions: ["24.2", "25.1", "25.2"]
    skill_revision: v2
    runner_module: sim_runners.fluent.pyfluent_038
    extras_alias: fluent-pyfluent-0-38
    notes: |
      Uses .general.material accessor (PyFluent 0.38+).
      Fluent 24.1 dropped upstream — DO NOT pick this profile for 24.1.

  - name: pyfluent_0_37_legacy
    sdk: ">=0.37,<0.38"
    solver_versions: ["24.1", "24.2", "25.1"]
    skill_revision: v1
    runner_module: sim_runners.fluent.pyfluent_037
    extras_alias: fluent-pyfluent-0-37
    notes: |
      Direct cell_zone.<zone>.material accessor.
      Last profile that supports Fluent 24.1.

# Profiles that are no longer maintained.
# Listed so resolution errors can hint at the right migration target.
deprecated:
  - profile: pyfluent_0_30_alpha
    reason: predates DriverProtocol; no longer maintained
    last_supported_in_sim_cli: "0.1"
    migrate_to: pyfluent_0_37_legacy
```

### 6.1 Field reference

| Field | Required | Meaning |
|---|---|---|
| `driver` | ✓ | Must match the driver's registered name in `drivers/__init__.py`. |
| `sdk_package` | ✓ | Distribution name as it appears on PyPI / the registry the driver pulls from. |
| `profiles[].name` | ✓ | Stable identifier. **Never rename** — agents and skill folders reference it. |
| `profiles[].sdk` | ✓ | PEP 440 specifier for the SDK version range. |
| `profiles[].solver_versions` | ✓ | Concrete solver versions tested against this SDK range. List, not range — version reporting from solvers is messy. |
| `profiles[].skill_revision` | ✓ | Identifier the skill folder uses to scope its `snippets/<rev>/` and `reference/<rev>/`. |
| `profiles[].runner_module` | ✓ | Python import path of the per-profile runner module that lives inside the profile env. |
| `profiles[].extras_alias` |   | Name of the matching `[project.optional-dependencies]` extra in pyproject.toml. Power users can `pip install sim-cli[<alias>]` to skip `sim env`. |
| `profiles[].notes` |   | Free-form, surfaced in `sim check` output. |
| `deprecated[]` |   | Old profile names + migration hints. |

### 6.2 Resolution rules

Given a detected solver version `V`:
1. Walk `profiles` in declaration order.
2. The first profile whose `solver_versions` contains `V` is the *preferred* match.
3. If no profile matches, return `unsupported` and surface the deprecated table for hints.
4. If multiple profiles match the same `V` (intentional overlap during migration), the first one wins; both are surfaced in `sim check` output for the user to override with `--profile`.

### 6.3 Versioning the schema itself

The schema version is implied by sim-cli version. Schema breaking changes require a sim-cli minor bump and a `version-compat-migration.md` note.

---

## 7. Driver protocol additions

Two new methods on `DriverProtocol`. Both are pure Python; neither imports the SDK.

```python
@dataclass(frozen=True)
class SolverInstall:
    name: str            # driver name, e.g. "fluent"
    version: str         # detected solver version, e.g. "25.2"
    path: str            # filesystem path to the installation root
    source: str          # how we found it: "env:AWP_ROOT252", "registry", "default-path"
    extra: dict          # driver-specific metadata (e.g. {"license_server": "..."})


class DriverProtocol(Protocol):
    name: str

    # ... existing methods (lint, connect, parse_output, run_file) ...

    def detect_installed(self) -> list[SolverInstall]:
        """Scan THIS host for installations of this driver's solver.

        Pure Python. Must NOT import the SDK. Must NOT launch the solver.
        Must be safe to call when nothing is installed (returns []).
        Should be cheap (≤ a few hundred ms) — it runs in interactive paths.
        """

    def runner_for_profile(self, profile_name: str) -> str:
        """Return the import path of the runner module for a given profile.

        Implemented as a small helper that reads compatibility.yaml.
        Provided by a default mixin so most drivers do not override it.
        """
```

### 7.1 Detection patterns by solver

Each driver gets a different scan strategy. The catalogue:

| Driver | Where to look |
|---|---|
| `fluent` | `AWP_ROOT*` env vars; `C:\Program Files\ANSYS Inc\v???\fluent\ntbin\win64\fluent.exe`; Windows registry key `HKLM\SOFTWARE\Ansys, Inc.\Fluent` |
| `comsol` | `C:\Program Files\COMSOL\COMSOL??\Multiphysics\bin\win64\comsol.exe`; macOS `/Applications/COMSOL Multiphysics ??.app`; `COMSOL_HOME` env var |
| `matlab` | Windows registry `HKLM\SOFTWARE\MathWorks\MATLAB\<release>`; `C:\Program Files\MATLAB\R????`; `which matlab` on Linux |
| `openfoam` | `WM_PROJECT_DIR` env var (the canonical OpenFOAM marker); `which simpleFoam` |
| `flotherm` | Windows registry `HKLM\SOFTWARE\Mentor Graphics\Flotherm`; default install dir |
| `ansa` | `C:\BETA_CAE_Systems\ansa_v??\ansa_win64.exe`; `ANSA_HOME` env var |
| `pybamm` | This one is special — PyBaMM is itself a pip package, not a separate solver binary. Detection means *importing* the package, so `pybamm` is the only driver where `detect_installed()` may import its SDK. |

These rules are stable across years; we encode them once.

---

## 8. The runner subprocess + IPC protocol

Each profile env contains a small `sim_driver_runner.<solver>` Python module. The core sim process spawns it as a subprocess and talks to it via JSON-over-stdio. This is the same trick LSP, DAP, MCP, and `pylance --stdio` use.

### 8.1 Process layout

```
sim-cli core process                       profile env
─────────────────────                      ─────────────────────────
sim CLI / sim serve                        .sim/envs/fluent-0-38/
   │                                          ├─ bin/python
   │                                          └─ site-packages/
   │                                              ├─ ansys-fluent-core 0.38.1
   │                                              └─ sim_driver_runner/
   │                                                    └─ fluent/
   │                                                          └─ pyfluent_038.py
   │
   │  spawn:
   │     <env>/bin/python -m sim_driver_runner.fluent.pyfluent_038
   │
   ▼
   stdin / stdout JSON pipes ◄────────────► runner main loop
```

The core process **never imports PyFluent**. All SDK imports happen inside the runner. This means:
- `sim` startup time stays fast as we add drivers
- A bug in PyFluent 0.38 cannot crash the sim core
- Multiple profiles can run side by side (one runner subprocess per active session)

### 8.2 Wire protocol

Newline-delimited JSON. Every message is a single line. One JSON object per line.

```json
// from core to runner
{"id": 1, "op": "handshake"}
{"id": 2, "op": "connect", "args": {"mode": "solver", "ui_mode": "gui", "processors": 2}}
{"id": 3, "op": "exec", "args": {"code": "solver.settings.mesh.check()", "label": "mesh-check"}}
{"id": 4, "op": "inspect", "args": {"name": "session.summary"}}
{"id": 5, "op": "disconnect"}
{"id": 6, "op": "shutdown"}

// from runner to core (responses)
{"id": 1, "ok": true, "data": {"sdk_version": "0.38.1", "solver_version": "25.2", "profile": "pyfluent_0_38_modern"}}
{"id": 2, "ok": true, "data": {"session_id": "f1f9..."}}
{"id": 3, "ok": true, "data": {"stdout": "...", "result": null, "elapsed_s": 0.42}}
{"id": 3, "ok": false, "error": {"type": "AttributeError", "message": "..."}}
```

### 8.3 Lifecycle

```
1. core: spawn runner
2. core → runner: {op: "handshake"}
3. runner → core: {ok: true, data: {sdk_version, solver_version, profile}}
4. core: validate against compatibility.yaml; abort if mismatch
5. core → runner: {op: "connect", args: {...}}
6. ... loop on exec / inspect ...
7. core → runner: {op: "disconnect"}
8. core → runner: {op: "shutdown"}
9. runner: graceful exit
```

If the runner dies between messages, the core marks the session as crashed and surfaces the runner's stderr in the next `sim ps` / `sim inspect` call. We do NOT auto-restart — agent should observe the crash and decide.

### 8.4 Why JSON-over-stdio (not gRPC, not sockets, not shared memory)

- **Zero infrastructure** — no port allocation, no firewall, no auth, no schema compiler
- **Same primitive LSP/DAP/MCP use** — well-trodden, lots of reference implementations
- **Trivial to debug** — `cat` the pipe, see human-readable JSON
- **Process isolation is automatic** — when the runner exits, its file descriptors close

Sockets become attractive when we want to share one runner across multiple core processes (which we don't), or for IPC across machines (`sim --host` already covers that case at a higher layer).

---

## 9. Subcommand changes

| Subcommand | Today | After M1 |
|---|---|---|
| `sim check <solver>` | Returns "installed yes/no" based on a Python import attempt | **Calls `detect_installed()` on local OR remote host (via `--host`); prints all installs + their resolved profiles + bootstrap status** |
| `sim env install <profile>` | does not exist | **Creates `.sim/envs/<profile>/` with the right SDK pinned, also installs the runner shim** |
| `sim env list` | does not exist | **Lists all bootstrapped envs and their state** |
| `sim env remove <profile>` | does not exist | **Removes a profile env** |
| `sim connect --solver <name>` | Direct in-process driver call; uses whatever SDK pip installed | **Detects, picks profile, ensures env exists, spawns runner subprocess, dispatches** |
| `sim inspect session.versions` | does not exist | **Returns `{sdk, solver, profile, env_path}`** |
| `sim ps` | shows `connected/mode/run_count` | also shows the active profile + env path |

### 9.1 `--host` is uniform

All subcommands that touch a solver accept `--host <ip>`. With `--host` set, the subcommand is a thin HTTP wrapper around an endpoint on the remote `sim serve`:

| Command | Endpoint |
|---|---|
| `sim --host X check fluent` | `GET /detect/fluent` |
| `sim --host X env install <profile>` | `POST /env/install` |
| `sim --host X env list` | `GET /env/list` |
| `sim --host X connect --solver fluent` | `POST /connect` (existing, extended) |

Without `--host`, the same code paths run locally. Same Python; different transport.

---

## 10. Skill side: what `sim-skills/` must do

Every skill protocol gets a mandatory **Step 0** before any solver-specific code:

> **Step 0 — Detect the runtime profile.** After `sim connect`, immediately run:
> ```bash
> sim --host <ip> inspect session.versions
> ```
> Read the returned `profile` field. Use it to choose which `<skill>/snippets/<profile>/*.py` and `<skill>/reference/<profile>/*.md` files to load. **Never read snippets from the wrong profile folder.** If `profile` is empty or unrecognized, stop and surface the version table to the user.

Skill folder layout becomes profile-aware:

```
sim-skills/fluent/
  SKILL.md                        ← protocol; version-agnostic; mandates Step 0
  compatibility.md                ← human-readable version of compatibility.yaml
  reference/
    common/                       ← rules that apply to ALL profiles
      input_classification.md
      acceptance_criteria.md
    pyfluent_0_38_modern/         ← per-profile reference
      boundary_conditions.md
    pyfluent_0_37_legacy/
      boundary_conditions.md
  snippets/
    common/                       ← profile-agnostic snippets
      00_mesh_check.py
    pyfluent_0_38_modern/
      05_set_material.py
    pyfluent_0_37_legacy/
      05_set_material.py
  workflows/
    common/
    pyfluent_0_38_modern/
      mixing_elbow.py
```

Snippet files MUST start with a metadata header:

```python
# profile: pyfluent_0_38_modern
# requires:
#   solver: in ["24.2", "25.1", "25.2"]
#   sdk: ">=0.38,<0.39"
```

`sim lint` parses this header and refuses to send a snippet to a session whose `profile` does not match. The agent gets a fail-fast error instead of an `AttributeError` ten lines into a Python exec.

The `sim-skills/CLAUDE.md` cross-skill conventions section gets a new mandatory rule (added in task #2 below):

> **Rule (runtime version awareness):** Step 0 of every skill protocol MUST be `sim inspect session.versions`. Snippets MUST be loaded from the matching profile folder. Reference docs in `<skill>/reference/<profile>/` override anything in `<skill>/reference/common/` for that profile.

---

## 11. Why this design and not the alternatives

| Alternative | Why we did not pick it |
|---|---|
| **Single SDK pin in `dependencies`** | Current state. The thing we are fixing. |
| **Per-release sim-cli pins** (`sim-cli 0.2 ⇔ Fluent 25R2`) | A workstation with Fluent 24R2 + 25R2 side by side has no way to use both. Also forces users to pin sim-cli to a specific solver version, which is the wrong direction. |
| **Per-(solver, version) separate driver classes** (`fluent@25`, `fluent@24`) | Code duplication explodes. Doesn't scale to 50 backends. Agents would have to learn dozens of driver names. |
| **Distribute as N separate packages** (`sim-fluent-modern`, `sim-fluent-legacy`) | dbt does this, but they have a corporate ecosystem maintaining each adapter. We are too small to maintain N release pipelines. |
| **Capability detection only, no version metadata** | Right asymptotic answer (browser-style polyfills) but enormous upfront cost. We adopt it gradually for high-frequency operations only — see §12. |
| **One universal venv with all SDKs side by side** | Many SDKs have mutually exclusive dependency closures (e.g. PyFluent 0.37 vs 0.38). Pip cannot resolve. |

The rejected ideas all collapse against either Axiom B (must detect at runtime) or Axiom C (must isolate per profile).

---

## 12. Future work (post-M1)

These are explicitly **not** in M1 but the design must not foreclose them.

- **Façade layer for high-frequency operations.** The driver could expose a stable cross-profile API for the ~10 most-used calls (e.g. `session.bc.set_velocity_inlet(...)`) and dispatch internally. Browser-polyfill style. Skill snippets that use the façade become version-agnostic. We add this when the maintenance pain of profile-specific snippets exceeds the cost of building façades.
- **CI matrix with self-hosted runners.** GitHub Actions matrix that expands `compatibility.yaml` into one job per (sdk_version, solver_version) cell, runs the relevant integration tests, and gates release on all green. Solver-license-required jobs run on a self-hosted runner inside the lab.
- **`sim env update` and lockfiles per profile.** Each `.sim/envs/<profile>/` carries its own `uv.lock` so SDKs are reproducible across machines. `sim env update <profile>` refreshes within the compatibility.yaml constraint window.
- **Auto-bootstrap on `sim connect --solver X`.** If no env is bootstrapped yet for the resolved profile, prompt or `--auto-install` to do it inline. Already in the M1 plan as task #9.
- **Cross-host detection caching.** When the user's day-to-day workflow targets one license server, cache that server's `detect/fluent` response for some short TTL.

---

## 13. M1 implementation roadmap (the contract for the rest of this work)

Each row is one task in the project task tracker. Order matters; later tasks depend on earlier ones.

| # | Task | Output | Risk |
|---|---|---|---|
| 1 | Write this doc | `docs/architecture/version-compat.md` | 0 |
| 2 | Update `sim-skills/CLAUDE.md` Step 0 rule | mandatory runtime detection rule | 0 |
| 3 | `compatibility.yaml` schema + Fluent's first version | yaml file + `sim/compat.py` loader | low |
| 4 | `Driver.detect_installed()` protocol + Fluent impl | new method on DriverProtocol; Fluent scanner | low |
| 5 | `sim check <solver>` on-demand local + remote | extended subcommand + `GET /detect/<solver>` endpoint | low |
| 6 | `sim env install/list/remove` | new subcommand; `.sim/envs/` management; uv preferred, stdlib fallback | medium |
| 7 | `sim_driver_runner` + JSON-over-stdio IPC | runner package + protocol implementation | **medium-high** |
| 8 | Refactor Fluent driver to dispatch through runner | thin client in core; PyFluent calls move to runner | medium |
| 9 | `sim connect` auto-bootstrap on first use + `inspect session.versions` | end-to-end happy path | medium |
| 10 | Update 4 READMEs + pyproject extras | docs catch up to the new install flow | 0 |

After M1 completes:
- The four-axis problem from §2 is **structurally solved** for Fluent
- Adding any other solver to this model is "fill in the same five files" (compatibility.yaml, detect_installed, runner module, skill snippet folders, README install line)
- We are positioned for the post-M1 work in §12 without further architectural changes

---

## 14. Glossary

- **Profile** — a named `(SDK version range, solver version list)` tuple defined in `compatibility.yaml`. The unit of compatibility throughout this design.
- **Profile env** — an isolated venv under `.sim/envs/<profile-name>/` containing the SDK pinned for one profile plus the matching runner module.
- **Runner** — the small Python program that lives inside a profile env, imports the SDK, and exposes a JSON-over-stdio interface to the core sim process.
- **Detect** — calling `driver.detect_installed()` (locally) or `GET /detect/<solver>` (remote) to enumerate solver installations on a host. Pure Python, no SDK required.
- **Bootstrap** — creating a profile env and installing the SDK + runner into it. Happens via `sim env install`.
- **Dispatch** — the core sim process spawning a runner subprocess and forwarding `connect`/`exec`/`inspect`/`disconnect` calls into it.
- **Skill revision** — a stable identifier (e.g. `v1`, `v2`) used as the folder name under `<skill>/snippets/` and `<skill>/reference/` to scope content to a profile.
