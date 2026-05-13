# Lifecycle control patterns

These are **control patterns** — agent decision logic, not code
templates. They cover the two sim-cli execution models; the driver
skill tells you which one applies.

---

# Part A — Persistent session (connect / exec / inspect / disconnect)

Used by any driver that holds a live process/session open.

## Pattern 0 — Session lifecycle

```
CONNECT → STEP-0 VERSION PROBE → [STEP × N] → DISCONNECT
```

- One session per task. Do not reuse a session across unrelated tasks.
- Connect with the correct core launch flags (`mode`, `ui-mode`,
  `processors`, `workspace`) and any plugin-owned `--driver-option`
  values documented by the driver skill. Mode cannot change mid-session.
- Always disconnect explicitly, even if steps failed.

## Pattern 1 — Connect + verify

**When**: at the start of every task.

1. Run `sim connect --solver <solver> [core launch flags] [--driver-option KEY=VALUE]...`.
2. Check exit code = 0.
3. Run `sim inspect session.summary`. Verify `connected=true`,
   `mode=<expected>`, `run_count=0`.
4. Run `sim inspect session.versions` → see
   [`version_awareness.md`](version_awareness.md). Use the returned
   `profile` / `active_sdk_layer` / `active_solver_layer` to pick the
   right subfolder inside the driver skill.

If verification fails: stop, report to the user. Do not proceed.

## Pattern 2 — Step execution loop

**When**: for each workflow step.

```
write code → sim exec --file <tmp> --label <label>
         ↓
     exit code?
       0 → sim inspect last.result → ok=true? → continue
                                   → ok=false? → STOP, report
       ≠0 → STOP, report
```

Each step is a checkpoint. The loop does not advance until the current
step is confirmed successful. Labels appear in `session.summary` and
log files — they are the audit trail. Use descriptive labels
(`import-geometry`, `surface-mesh`, `hybrid-init`) not generic ones
(`step1`, `run`).

## Pattern 3 — State query

**When**: after any step that changes session state, or when verifying
a precondition for the next step.

See [`command_surface.md`](command_surface.md) for the full list of
`sim inspect` targets. Do not skip inspects between steps that depend
on each other — e.g. do not send a volume-mesh step before confirming
surface-mesh succeeded.

## Pattern 6 — Disconnect + report

**When**: at the end of every task (success or failure).

1. Run `sim disconnect`.
2. Report:
   - Solver and mode.
   - Steps completed (labels and final `run_count`).
   - Key extracted values (cell count, residuals, integral quantities, …).
   - Whether the driver skill's acceptance checklist was satisfied.
   - Any warnings or non-fatal issues observed in stdout.

Format: structured summary, not a narrative. Values should be explicit.

---

# Part B — One-shot batch (run / parse / evaluate)

Used by drivers that execute one input/script and exit.

## Pattern 0 — Execution model

```
VALIDATE → RUN → EVALUATE → REPORT
```

There is no live session. The entire solve is one blocking `sim run …`
call. All agent decisions happen **before** the call (input validation,
acceptance-criterion confirmation) and **after** (output parsing,
acceptance evaluation).

## Pattern 1 — Validate before running

**When**: before every `sim run` call.

1. Classify inputs per
   [`input_classification.md`](input_classification.md) and ask for any
   missing Category A inputs — especially the acceptance criterion.
2. Optionally call the driver's lint/check hook if the driver skill
   documents one.
3. Confirm the input files exist and are readable.

If any check fails: stop. Report the specific failure. Do not call
`sim run`.

## Pattern 2 — Run and capture

```bash
sim run <script_or_deck> --solver <solver>
# exit code, stdout, stderr, parsed_output returned on the result object
```

This call blocks until the solver exits. It may take seconds to hours.
Do not assume a timeout — the solver manages its own execution, and a
parent timeout that kills a long solve mid-run can leave an inconsistent
workdir.

## Pattern 3 — Evaluate output

**When**: after `sim run` returns.

```
exit_code?
  0  → check stderr for ERROR lines → check stdout non-empty → parse_output()
                                                             → evaluate vs acceptance
  ≠0 → STOP. Report exit_code + stderr. Task incomplete.
```

Structured data extraction uses the driver's `parse_output()` hook,
which returns the last JSON object found in stdout (or `{}` if none).
The driver skill tells you what fields to expect.

## Pattern 4 — Report

Same as Part A's Pattern 6, minus the `disconnect` step.

---

# Part C — Shared across both models

## Acceptance evaluation

See [`acceptance.md`](acceptance.md). Exit code and `ok=true` are
necessary but not sufficient. Always evaluate against an outcome-based
criterion from the driver skill's acceptance checklist.

## Failure handling

See [`escalation.md`](escalation.md). Never silently retry. When a step
fails, capture `stderr`, `stdout`, and the completion state; report to
the user; let them decide the next move.
