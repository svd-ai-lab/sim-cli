---
name: sim-cli
description: Cross-solver operating discipline for sim-cli workflows — tool choice, input classification, acceptance semantics, and escalation rules that apply across solvers. Use alongside the solver's own plugin skill, which is self-contained for solver-specific work; this skill carries only the shared rules.
---

# sim-cli

You are working in a **sim-cli**-enabled solver workflow. Use the `sim`
runtime where it adds control and observability, and compose solver-native
tools directly where they are the right primitive. This skill carries the
**cross-solver discipline** — the rules that hold across sim-cli workflows,
regardless of which solver you drive.

The solver's **plugin skill** is self-contained for solver-specific work:
solver hard constraints, dependency chains, snippets, workflows, SDK/solver
notes. It does not depend on loading this skill — but it should stay
consistent with the discipline below. If a rule applies to more than one
solver, it belongs here, not in a plugin skill.

---

## Execution models

The plugin skill tells you which model the solver uses. Choose the narrowest
correct execution primitive; sim-cli is composable, not a universal wrapper.

| Model | Used by | Lifecycle |
|---|---|---|
| **Persistent session** | Drivers that hold a live process open | `sim connect → sim exec × N → sim inspect → sim disconnect` |
| **sim-wrapped one-shot batch** | Plugin wrappers that add linting, profile-aware invocation, parsing, history, or safer execution | `sim check → sim run → parse_output/logs → evaluate` |
| **Native/tool one-shot batch** | Ready solver decks/scripts, vendor batch commands, project pipelines, or post-processing tools where native execution is the right primitive | version/profile probe → native command/script → parse artifacts/logs → evaluate |

sim-cli does **not** try to wrap every solver operation, executable flag,
vendor batch mode, or post-processing script. Use `sim` when it adds a stable
control plane: solver discovery and profile checks, live sessions, bounded
`exec` / `inspect` loops, history/log capture, parsing, screenshots, or shared
agent discipline. If the artifact is already a solver-native deck/script and
the solver's own batch command is the right execution primitive, call that
native command directly instead of forcing it through `sim run`. Preserve
stdout/stderr, generated files, and acceptance evidence just as carefully.

Use `sim run` when the plugin skill says it is the canonical one-shot path or
when the wrapper adds real value. Otherwise, keep the sim-cli discipline while
composing the solver's native tools directly.

**The loop, any model:** classify inputs and get the missing Category A values
from the user (including the acceptance criterion) → choose the execution
primitive → run a Step-0 version/profile probe (`sim inspect session.versions`
for persistent sessions; `sim check <solver>`, plugin guidance, or native
`--version` / license probe for one-shot work) → execute one bounded step at a
time → inspect `last.result` or parse the native logs/artifacts between steps →
evaluate against the acceptance criterion → `sim disconnect` if a persistent
session was opened. On any failure, stop and report — do not silently retry.

---

## Hard constraints (shared sim-cli discipline)

1. **Never invent Category A defaults.** Physical decisions — geometry,
   materials, boundary conditions, the acceptance criterion — must come from
   the user. "Just use defaults" / "just run it" does not override this;
   treat it as a missing input and ask.
2. **Step-0 version/profile probe is mandatory.** After `sim connect`, call
   `sim inspect session.versions` and use the returned `profile` /
   `active_sdk_layer` / `active_solver_layer` to pick the right files in the
   plugin skill. Before `sim run` or native one-shot execution, run the
   relevant probe for that path (`sim check <solver>`, plugin guidance, or the
   solver's native `--version` / license check). If a required profile is empty,
   unknown, or deprecated — **stop**.
3. **Acceptance ≠ exit code.** A `sim run` / `sim exec` / native solver command
   can return success and still be physically wrong. Always validate against an
   outcome-based, bounded, measurable criterion — not "the solver ran".
4. **Never silently retry a failed step.** Report `stderr`, `stdout`, and
   `run_count` / completion state / relevant artifact state; let the user
   decide the next move.
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
| **C — file-derivable** | **Infer from the actual files** via a diagnostic `sim exec`, solver-native inspection command, or artifact parser — not from a similar example. Confirm if a downstream decision depends on it. | Mesh cell count, boundary names/types, fields present in a result file, material IDs |

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
