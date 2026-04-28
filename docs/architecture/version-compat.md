# Version Compatibility & Plugin Discovery

> **Status:** stub.
> **Audience:** sim-cli maintainers, plugin authors.
> **Last reviewed:** 2026-04-27.

This document used to carry a long, driver-specific compatibility-matrix design. Most of that material now lives **inside individual plugin packages** — every commercial-solver driver ships as its own out-of-tree plugin, and each plugin owns the version-compat data for its own SDK and solver releases. The design intent is preserved here in summary form so the public `sim-cli-core` repo still describes the contract that plugins implement.

If you are looking for the per-plugin compatibility data, read each plugin's own `compatibility.yaml` and its own architecture notes.

---

## 1. Why "compatibility" is plural

Every supported solver has its own version sprawl, each with its own SDK or scripting interface that pins to a narrow window of solver versions, and each with skill content that is implicitly tied to a specific API surface. A single global pin in `pyproject.toml` cannot represent that. We solve it by:

- shipping a small **core** runtime (`sim-cli-core`) that holds no solver SDK as a hard dependency,
- letting each driver — built-in or external — carry its own `compatibility.yaml` next to its `driver.py`,
- discovering external drivers at import time through a standard Python entry-point group.

---

## 2. Plugin discovery contract

Two channels feed `get_driver(name)` in `src/sim/drivers/__init__.py`:

1. **`_BUILTIN_REGISTRY`** — an ordered list of `(name, "module:Class")` tuples for the open-source drivers shipped in this repo (PyBaMM, OpenFOAM, CalculiX, gmsh, SU2, LAMMPS, Elmer, scikit-fem, MFEM, OpenSeesPy, SfePy, OpenMDAO, FiPy, pymoo, Pyomo, SimPy, Trimesh, Devito, CoolProp, scikit-rf, pandapower, ParaView, meshio, PyVista, Newton, Isaac Sim, LTspice, …).
2. **`sim.drivers` entry-point group** — external packages register drivers via standard Python entry points:

   ```toml
   # in the plugin package's pyproject.toml
   [project.entry-points."sim.drivers"]
   myname = "my_pkg.module:MyDriver"
   ```

   At import time, sim-cli enumerates the group, validates each spec shape, drops collisions with built-ins (built-ins always win), and appends the survivors after the built-in list. Resolution is lazy: a broken plugin module does not crash the CLI, and `get_driver` raises the original `ImportError` only if the user asks for that specific driver.

The list of drivers a given install can see is therefore a function of `_BUILTIN_REGISTRY` plus whatever plugin packages are installed in the same venv. Run `sim solvers list` to see the resolved set.

---

## 3. `compatibility.yaml` — per-driver

Each driver folder may contain a `compatibility.yaml` that declares the SDK versions, solver versions, and skill-layer slugs it supports. This is the unit of compatibility throughout the runtime: a driver is compatible with a given solver install when at least one of its profiles matches.

```yaml
# src/sim/drivers/<name>/compatibility.yaml  (or inside a plugin package)
driver: <name>
sdk_package: <pypi-distribution-name>          # may be omitted for SDK-less drivers

profiles:
  - name: <stable-identifier>
    sdk: ">=X.Y,<Z.W"                          # PEP 440 specifier, optional
    solver_versions: [...]                     # concrete solver versions tested
    runner_module: <python-import-path>        # optional runner subprocess
    active_sdk_layer: <slug>                   # optional, for sim-skills overlays
    active_solver_layer: <slug>                # optional, for sim-skills overlays
    notes: |
      Free-form notes surfaced in `sim check` output.

deprecated:
  - profile: <old-profile-name>
    reason: ...
    migrate_to: <newer-profile-name>
```

Field rules:

| Field | Required | Meaning |
|---|---|---|
| `driver` | yes | Must match the driver's registered name. |
| `sdk_package` | no | Distribution name on PyPI / the index the driver depends on, when one exists. |
| `profiles[].name` | yes | Stable identifier — never rename, agents and skill folders reference it. |
| `profiles[].sdk` | no | PEP 440 specifier for the SDK version range. |
| `profiles[].solver_versions` | no | Concrete solver versions tested against this profile. |
| `profiles[].runner_module` | no | Import path of the per-profile runner module that lives inside an isolated env. |
| `profiles[].active_sdk_layer` | no | Slug of the matching `sim-skills/<driver>/sdk/<slug>/` layer. |
| `profiles[].active_solver_layer` | no | Slug of the matching `sim-skills/<driver>/solver/<slug>/` layer. |
| `profiles[].notes` | no | Surfaced in `sim check`. |
| `deprecated[]` | no | Old profile names + migration hints. |

### Resolution

Given a detected solver version `V`:

1. Walk `profiles` in declaration order.
2. The first profile whose `solver_versions` contains `V` wins.
3. If no profile matches, return `unsupported` and surface the deprecated table for hints.
4. Multiple matches — first wins, but `sim check` surfaces all of them so the user can override with `--profile`.

---

## 4. Detection and bootstrap

The user-facing flow stays per-solver and lazy:

1. `sim check <solver>` calls the driver's `detect_installed()` (pure stdlib, no SDK import) on the local host or, with `--host`, on a remote `sim serve` over `GET /detect/<solver>`. It reports installs and resolved profiles; it does **not** install anything.
2. `sim env install <profile>` (when implemented for that driver) creates an isolated venv under `.sim/envs/<profile>/`, pins the SDK inside it, and installs the runner module that talks JSON-over-stdio to the core.
3. `sim connect --solver <name>` picks the matching profile, ensures the env exists, and dispatches.

The core sim process never imports any solver SDK directly — all SDK imports happen inside the runner subprocess, so a bug in one SDK cannot crash the core, and side-by-side multi-version installs are natural.

---

## 5. Profile environments and runner subprocesses

When a driver opts into a profile env, its layout is:

```
sim-cli-core process                   profile env
─────────────────────                  ─────────────────────────
sim CLI / sim serve                    .sim/envs/<profile>/
   │                                       ├─ bin/python
   │  spawn: <env>/bin/python -m            └─ site-packages/
   │         <runner_module>                     ├─ <SDK pinned>
   ▼                                              └─ sim_driver_runner/<driver>/
   stdin/stdout JSON pipes ◄─────────► runner main loop
```

The wire protocol is newline-delimited JSON over stdin/stdout; one message per line. Operations: `handshake`, `connect`, `exec`, `inspect`, `disconnect`, `shutdown`. Errors come back as `{"id": N, "ok": false, "error": {...}}`.

This is the same primitive LSP, DAP, and MCP use. It costs no port allocation, no firewall, no auth, and it isolates SDKs that have mutually exclusive dependency closures. Runner death is treated as session crash — sim does not auto-restart; the agent observes and decides.

---

## 6. Where the rest of the design lives

Per-driver compatibility matrices, detection patterns, and runner implementations live in the driver itself — inside this repo for built-in OSS drivers, inside the plugin package for everything else. The public `sim-cli-core` repo intentionally stays thin and version-agnostic; it owns the contract, not the data.

For the layered skill-content design that consumes `active_sdk_layer` / `active_solver_layer`, see [`skills-layering-plan.md`](skills-layering-plan.md).
