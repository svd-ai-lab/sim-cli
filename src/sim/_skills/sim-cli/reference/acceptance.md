# Acceptance semantics

Across every sim-cli driver: **`exit_code == 0` alone does not satisfy
acceptance.** A simulation can return `ok=true` and still be physically
wrong — diverged but quietly, converged to the wrong basin, ran the
correct model with the wrong BCs, hit the iteration cap before
residuals dropped.

Acceptance is always outcome-based.

---

## The distinction

> "The script ran without error" ≠ task complete.
> "The acceptance checklist is satisfied" = task complete.

Exit code and `ok=true` are *preconditions*, not *acceptance*. If exit
code is non-zero, acceptance cannot possibly be met; if it is zero,
acceptance still has to be checked.

---

## What counts as an acceptance criterion

A good criterion is **outcome-based**, **bounded**, and **measurable**:

- Outcome: describes the physical result, not the operation
  (✅ "outlet temperature in 28–35 °C"; ❌ "the solver ran for 150 iterations")
- Bounded: has an explicit tolerance or range, not just a target
- Measurable: extractable from the solver via `sim inspect last.result`
  (persistent) or `parse_output(stdout)` (one-shot)

Examples by physics:

| Domain | Good criterion |
|---|---|
| Thermal | Max junction T < 85 °C; peak T within ±2 K of reference |
| CFD / flow | Outlet mass-flow balance within 1 % of inlet; all RMS residuals < 1e-4 |
| Structural | Tip displacement within 5 % of analytical / reference |
| Meshing | Min orthogonal quality > 0.2; max aspect ratio < 50 |
| Battery | End-of-discharge voltage within 10 mV of reference |
| Optimization | Pareto front has ≥ N non-dominated points at generation G |

---

## Where criteria live

Each driver skill ships an `acceptance_checklists.md` (or equivalent
per-workflow README) under `base/reference/` or `base/workflows/`.
Those define the canonical criteria for each packaged workflow.

For **user-supplied tasks** (not a packaged workflow), the acceptance
criterion is a **Category A input** — ask the user for it. See
[`input_classification.md`](input_classification.md).

Acceptable shapes of a user answer:

- "Max junction temp must be under 85 °C." ← outcome-based ✅
- "Outlet mass flow within 1 % of inlet." ← outcome-based ✅
- "Just run it." ← operation-based, **treat as missing Category A** ❌
- "Let me know when it's done." ← operation-based, ❌

---

## Evaluation loop

After the final step (persistent) or the single `sim run` return
(one-shot):

1. Verify preconditions: exit_code == 0, `ok=true`, `stderr` free of
   ERROR lines.
2. Extract the numeric value(s) the criterion needs — via
   `sim inspect last.result` or `parse_output(stdout)`.
   The acceptance check itself can be a python computation against output
   files, a sim inspect query against the live session, or a vendor-script
   invoked via sim run — pick whichever is closest to where the data lives.
3. Compare against the criterion. Record the comparison explicitly in
   the final report: "`T_max = 82.3 °C` — criterion `< 85 °C` ✅".
4. If any criterion fails — task is **INCOMPLETE**. Report which
   criterion failed, the extracted value, and the gap.

---

## Acceptance vs escalation

This file covers the "happy path" final check. If a step *fails
outright* (non-zero exit, `ok=false`, exception in stderr), see
[`escalation.md`](escalation.md) — that is not an acceptance failure,
it is an execution failure, and it has its own reporting protocol.
