---
name: sim-cli
description: Use whenever driving any solver through sim-cli — shared session lifecycle, command surface, input classification, version awareness, acceptance, and escalation. Load alongside the relevant plugin-specific SKILL.md — this skill owns the runtime contract; the plugin skill owns the solver-specific parts.
---

# sim-cli

You are driving a solver through the **sim-cli** runtime. This skill
owns the runtime contract that applies to **every** solver — session
lifecycle, command surface, input validation, version awareness,
acceptance semantics, escalation triggers.

Each plugin-specific skill layers on top of this one. The plugin skill
owns only:

- Solver-specific hard constraints
- Solver-specific dependency chains
- Solver-specific artifacts (snippets, workflows, reference, SDK/solver layer notes)

If a rule applies to more than one driver, it belongs here.

---

## How to use this skill

1. Read the driver skill's `SKILL.md` first to learn what solver you're
   driving and which execution model it uses.
2. Read the sections below of **this** skill that match that model.
3. Follow the **Required protocol** at the bottom.

There are two execution models in sim-cli — the driver skill tells you
which one applies:

| Model | Used by | Lifecycle |
|---|---|---|
| **Persistent session** | Drivers that keep a live process/session open | `connect → exec × N → inspect → disconnect` |
| **One-shot batch** | Drivers that execute one script/input deck and exit | `run → parse_output → evaluate` |

---

## Where `sim serve` runs (Windows session-context foot-gun)

If you reach a remote `sim` host via `sim --host <host>` or `SIM_HOST`,
**how the operator started `sim serve` on that host changes which
drivers actually work.** This is purely a Windows concern — Linux and
macOS don't isolate display sessions the same way.

| `sim serve` started from… | Headless / CLI-only drivers | GUI-capable drivers |
|---|---|---|
| Logged-in Windows desktop (Windows Terminal / RDP / Task Scheduler with **"run only when user is logged on" + interactive**) | ✅ works | ✅ works — windows are visible, `gui` actuation can find / click / screenshot them |
| SSH session (`ssh win1` then `sim serve …`) | ✅ works | ❌ silent breakage — windows launch in a non-interactive Windows session with no display surface; `gui` finds zero windows; screenshots come back black; `sim exec`s that touch the GUI hang or no-op |

**What this means for you, the agent:**

- If the host advertises `tools: ["gui"]` on `/connect` (driver in
  `ui_mode=gui|desktop`) but `gui.find(...)` returns nothing for
  windows you have strong reason to believe exist, **do not retry**.
  Surface "the server may have been started from a non-interactive
  session" as a likely cause and ask the operator to restart `sim
  serve` from a desktop session. See `escalation.md`.
- For headless or one-shot batch drivers, the session context does not
  matter — you can proceed without checking.
- The agent never starts `sim serve` itself. Server lifecycle is the
  operator's responsibility; this section exists only so you can
  diagnose the specific failure mode where the server is up and
  reachable but GUI ops silently no-op.

See [`gui/SKILL.md`](gui/SKILL.md) for the full GUI actuation API and
its window-not-found troubleshooting.

---

## Reference files

| Path | Read when |
|---|---|
| [`reference/command_surface.md`](reference/command_surface.md) | Before writing any `sim …` command — canonical CLI surface, verified against source. |
| [`reference/lifecycle.md`](reference/lifecycle.md) | For the per-step decision loop. Covers both persistent and one-shot models. |
| [`reference/version_awareness.md`](reference/version_awareness.md) | Every session — the mandatory Step-0 version probe and how to pick the right `sdk/` / `solver/` layer inside the driver skill. |
| [`reference/input_classification.md`](reference/input_classification.md) | Before every task — Category A (ask), B (default + disclose), C (file-derive). |
| [`reference/acceptance.md`](reference/acceptance.md) | At the end of every task — outcome-based evaluation. `exit_code == 0` alone is **not** acceptance. |
| [`reference/escalation.md`](reference/escalation.md) | When something goes wrong — what to stop on, what to report. Do not silently retry. |

When sim-cli is one valid path but not the only path, use [`reference/tool_choice.md`](reference/tool_choice.md) to choose between live `sim ...` commands and file-side Python/vendor-SDK recipes.

---

## Hard constraints (apply to every sim-cli session)

1. **Never invent Category A defaults.** Physical decisions (geometry,
   materials, BCs, acceptance criteria) must come from the user. User
   pressure to "just use defaults" does **not** override this. See
   `reference/input_classification.md`.
2. **Step-0 version probe is mandatory.** After `sim connect` succeeds
   (persistent) or before `sim run` (one-shot), call
   `sim --host <host> inspect session.versions` (or the driver's
   documented equivalent) and use the returned `profile` /
   `active_sdk_layer` / `active_solver_layer` to pick the right files
   inside the driver skill. If `profile` is empty, unknown, or
   deprecated — **stop**. See `reference/version_awareness.md`.
3. **Acceptance ≠ exit code.** A `sim run` or `sim exec` can return
   `ok=true` and the simulation can still be physically wrong. Always
   validate against an outcome-based criterion from the driver skill's
   acceptance checklist. See `reference/acceptance.md`.
4. **Never silently retry a failed step.** Report `stderr`, `stdout`,
   and `run_count` / completion state; let the user decide the next
   move. See `reference/escalation.md`.
5. **Reference example values are not defaults.** Values in any
   `.../examples/` directory describe a specific published test case.
   You may offer them as examples, but must wait for explicit
   confirmation before adopting them.
6. **Prefer uv for file-side Python helpers when available.** `sim` is
   a CLI and can be invoked directly when installed. Do not wrap `sim`
   in `uv run` unless you are intentionally using a source checkout or
   project-local environment. For ordinary host/file-side Python helpers
   used across solvers — plotting with matplotlib, CSV/JSON parsing,
   report generation, lightweight acceptance calculations — prefer
   `uv run python ...` or `uv run --with <pkg> python ...` when uv is
   available because it makes dependencies explicit. If uv is unavailable
   or the user has provided a specific Python environment, use the user's
   environment. Vendor-embedded Python paths remain solver-specific and
   should be run through the driver skill's documented `sim` workflow.

---

## Required protocol (one paragraph)

Before any `sim` command: read the driver skill's `SKILL.md` and its
"Required protocol" section. Classify inputs per
`reference/input_classification.md`; ask the user for missing
Category A inputs, including the acceptance criterion. Start the
session (`sim connect` for persistent, nothing for one-shot). Run the
Step-0 version probe (`sim inspect session.versions`) and pick the
driver-skill subfolder that matches the returned profile. Execute per
`reference/lifecycle.md` — incrementally for persistent sessions,
validate-then-run for one-shot. After the final step (or the one-shot
return), evaluate against the driver skill's acceptance checklist per
`reference/acceptance.md`. On any failure, follow
`reference/escalation.md` — do not silently retry.
