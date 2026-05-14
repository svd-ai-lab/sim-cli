# Version Compatibility & Plugin Discovery

> **Status:** current.
> **Audience:** sim-cli maintainers, plugin authors.
> **Last reviewed:** 2026-05-11.

This document used to carry a long, driver-specific compatibility-matrix design. Most of that material now lives **inside individual plugin packages**. Each plugin owns the version-compat data for its own runtime dependencies. The design intent is preserved here in summary form so the public `sim-cli-core` repo still describes the contract that plugins implement.

If you are looking for the per-plugin compatibility data, read each plugin's own `compatibility.yaml` and its own architecture notes.

---

## 1. Why "compatibility" is plural

Every supported solver has its own version sprawl, each with its own SDK or scripting interface that pins to a narrow window of solver versions, and each with skill content that is implicitly tied to a specific API surface. A single global pin in `pyproject.toml` cannot represent that. We solve it by:

- shipping a small **core** runtime (`sim-cli-core`) that holds no solver SDK as a hard dependency,
- letting each solver plugin carry its own `compatibility.yaml` next to its `driver.py`,
- discovering installed solver plugins at import time through a standard Python entry-point group.

---

## 2. Plugin discovery contract

`get_driver(name)` in `src/sim/drivers/__init__.py` is fed by the
`sim.drivers` entry-point group. Solver plugins register drivers via standard
Python entry points:

```toml
# in the plugin package's pyproject.toml
[project.entry-points."sim.drivers"]
myname = "my_pkg.module:MyDriver"
```

At import time, sim-cli enumerates the group, validates each spec shape, and
records the surviving `module:Class` strings. Resolution is lazy: a broken
plugin module does not crash the CLI, and `get_driver` raises the original
`ImportError` only if the user asks for that specific driver.

The list of drivers a given `sim` executable can see is therefore a function of
the plugin packages installed in the Python environment running `sim`. Plugins
are independent Python distributions, but they are not discovered from a
separate plugin environment in the current CLI. Run `sim plugin list` or
`sim check --all` to see the resolved set.

---

## 3. `compatibility.yaml` — per-driver

Each plugin package may contain a `compatibility.yaml` that declares the SDK
versions, solver versions, and skill-layer slugs it supports. This is the unit
of compatibility throughout the runtime: a driver is compatible with a given
solver install when at least one of its profiles matches.

```yaml
# sim_plugin_<name>/compatibility.yaml
driver: <name>
sdk_package: <pypi-distribution-name>          # may be omitted for SDK-less drivers

profiles:
  - name: <stable-identifier>
    sdk: ">=X.Y,<Z.W"                          # PEP 440 specifier, optional
    solver_versions: [...]                     # concrete solver versions tested
    active_sdk_layer: <slug>                   # optional, for skill overlays
    active_solver_layer: <slug>                # optional, for skill overlays
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
| `profiles[].active_sdk_layer` | no | Slug of the matching `<skills-root>/<driver>/sdk/<slug>/` layer. |
| `profiles[].active_solver_layer` | no | Slug of the matching `<skills-root>/<driver>/solver/<slug>/` layer. |
| `profiles[].notes` | no | Surfaced in `sim check`. |
| `deprecated[]` | no | Old profile names + migration hints. |

### Resolution

Given a detected solver version `V`:

1. Walk `profiles` in declaration order.
2. The first profile whose `solver_versions` contains `V` wins.
3. If no profile matches, return `unsupported` and surface the deprecated table for hints.
4. Multiple matches — first wins, but `sim check` surfaces all of them so the user can override with `--profile`.

---

## 4. Current detection and bootstrap

The user-facing flow stays per-solver and lazy:

1. `sim check <solver>` calls the driver's `detect_installed()` (pure stdlib, no SDK import) on the local host or, with `--host`, on a remote `sim serve` over `GET /detect/<solver>`. It reports installs and resolved profiles; it does **not** install anything.
2. `sim connect --solver <name>` resolves the driver from the plugin entry point, attaches any matching compatibility profile to the session response, and dispatches through `DriverProtocol`.

The current CLI does not create per-profile plugin environments. The `sim`
process or `sim serve` process imports the plugin package from its own Python
environment. Individual plugins may still launch external solver processes or
manage their own subprocesses, but plugin discovery itself is in-process.

---

## 5. Possible future profile environments

The following remains a design direction for plugins that need strong SDK
isolation. It is not the current behavior of package installation or
`sim connect`; add plugin packages to the uv project with `uv add`.

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

This is the same primitive LSP, DAP, and MCP use. It costs no port allocation,
no firewall, no auth, and would isolate SDKs that have mutually exclusive
dependency closures. Runner death would be treated as session crash — sim would
not auto-restart; the agent observes and decides.

---

## 6. Where the rest of the design lives

Per-driver compatibility matrices and detection patterns live in plugin
packages. The public `sim-cli-core` repo intentionally stays thin and
version-agnostic; it owns the contract, not the data.

For the layered skill-content design that consumes `active_sdk_layer` / `active_solver_layer`, see [`skills-layering-plan.md`](skills-layering-plan.md).
