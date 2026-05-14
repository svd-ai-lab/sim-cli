---
name: sim-cli
description: Cross-solver operating discipline for sim-cli sessions — input classification, acceptance semantics, and escalation rules that apply to every solver. Use alongside the solver's own plugin skill, which is self-contained for solver-specific work; this skill carries only the shared rules.
---

# sim-cli

You are driving a solver through the **sim-cli** runtime. This skill carries
the **cross-solver discipline** — the rules that hold for every sim-cli
session, regardless of which solver you drive.

The solver's **plugin skill** is self-contained for solver-specific work:
solver hard constraints, dependency chains, snippets, workflows, SDK/solver
notes. It does not depend on loading this skill — but it should stay
consistent with the discipline below. If a rule applies to more than one
solver, it belongs here, not in a plugin skill.

---

## Execution models

The plugin skill tells you which model the solver uses:

| Model | Used by | Lifecycle |
|---|---|---|
| **Persistent session** | Drivers that hold a live process open | `connect → exec × N → inspect → disconnect` |
| **One-shot batch** | Drivers that run one script/deck and exit | `run → parse_output → evaluate` |

**The loop, either model:** classify inputs and get the missing Category A
values from the user (including the acceptance criterion) → start the session
(`sim connect`, or nothing for one-shot) → Step-0 version probe
(`sim inspect session.versions`) → execute one bounded step at a time,
inspecting `last.result` between steps → evaluate against the acceptance
criterion → `sim disconnect`. On any failure, stop and report — do not
silently retry.

---

## Hard constraints (every sim-cli session)

1. **Never invent Category A defaults.** Physical decisions — geometry,
   materials, boundary conditions, the acceptance criterion — must come from
   the user. "Just use defaults" / "just run it" does not override this;
   treat it as a missing input and ask.
2. **Step-0 version probe is mandatory.** After `sim connect` (persistent) or
   before `sim run` (one-shot), call `sim inspect session.versions` and use
   the returned `profile` / `active_sdk_layer` / `active_solver_layer` to pick
   the right files in the plugin skill. If `profile` is empty, unknown, or
   deprecated — **stop**.
3. **Acceptance ≠ exit code.** A `sim run` / `sim exec` can return `ok=true`
   and still be physically wrong. Always validate against an outcome-based,
   bounded, measurable criterion — not "the solver ran".
4. **Never silently retry a failed step.** Report `stderr`, `stdout`, and
   `run_count` / completion state; let the user decide the next move.
5. **Reference example values are not defaults.** Values in any `examples/`
   directory describe a specific published test case. Offer them explicitly
   if useful, but wait for the user's confirmation before adopting them.

---

## Input classification

Every task starts with: which inputs must the user supply, which may I
default, which can I derive from the files in front of me?

| Category | Rule | Examples |
|---|---|---|
| **A — physical decisions** | **Must ask if absent.** Non-negotiable. | Geometry, materials, boundary/initial conditions, physics-model choices, the acceptance criterion |
| **B — operational** | **May default — must disclose.** Affects runtime/convenience, not what the simulation represents. | `--processors`, `--ui-mode`, `--workspace`, smoke-test iteration counts, log verbosity |
| **C — file-derivable** | **Infer from the actual files** via a diagnostic `sim exec` — not from a similar example. Confirm if a downstream decision depends on it. | Mesh cell count, boundary names/types, fields present in a result file, material IDs |

Do not start until every Category A field has an explicit value from the user.

---

## Where `sim serve` runs (Windows session-context foot-gun)

If you reach a remote `sim` host via `sim --host <host>` or `SIM_HOST`, **how
the operator started `sim serve` changes which drivers actually work.** This
is purely a Windows concern — Linux and macOS don't isolate display sessions
the same way.

| `sim serve` started from… | Headless / CLI drivers | GUI-capable drivers |
|---|---|---|
| Logged-in Windows desktop (Windows Terminal / RDP / Task Scheduler "run only when user is logged on" + interactive) | ✅ works | ✅ works — windows are visible; `gui` can find / click / screenshot them |
| SSH session (`ssh <host>` then `sim serve …`) | ✅ works | ❌ silent breakage — windows launch in a non-interactive session with no display surface; `gui` finds zero windows, screenshots come back black |

If the host advertises `tools: ["gui"]` but `gui.find(...)` returns nothing
for windows you have strong reason to believe exist, **do not retry** —
surface "the server may have been started from a non-interactive session" and
ask the operator to restart `sim serve` from a desktop session. The agent
never starts `sim serve` itself.

See [`gui/SKILL.md`](gui/SKILL.md) for the full GUI actuation API.
