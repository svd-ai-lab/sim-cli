# Acceptance Checklists — flotherm-sim Phase A

> These checklists define what "task complete" means for each workflow type.
> A task is complete when ALL applicable [REQUIRED] items pass — not when exit_code=0.

---

## Pre-Execution Gate

Before running `run_file`, verify:

- [ ] `.pack` file path confirmed and file exists on disk
- [ ] `driver.lint()` returned `ok=True`
- [ ] `driver.connect()` returned `status="ok"`
- [ ] Acceptance criterion is outcome-based (not just "run it"):
  - ✅ "exit_code=0 with non-empty stdout"
  - ✅ "max junction temperature < 85°C (from parsed output)"
  - ✅ "solve completes in under 10 minutes"
  - ❌ "just run it" — not an outcome criterion
  - ❌ "see what happens" — same

If no valid acceptance criterion exists, ask the user:
> "What result do you want to verify? How will you judge whether this simulation succeeded?"

---

## Checklist 1 — Batch Solve Completion

### RunResult Fields
- **[REQUIRED]** `result.exit_code == 0`
- **[REQUIRED]** `result.duration_s > 0` (solve was measured)
- **[REQUIRED]** `result.stdout` is non-empty
- **[REQUIRED]** `result.solver == "flotherm"`
- **[RECOMMENDED]** `result.stderr` is empty or contains only non-ERROR lines

### Acceptance Criterion
- **[REQUIRED if output criterion stated]** `parse_output(result.stdout)` returns non-empty dict
- **[REQUIRED if output criterion stated]** The criterion value is present and compared — not just "see stdout"
- **[REQUIRED if output criterion stated]** Comparison result explicitly reported: PASS or FAIL with actual value

### What "task complete" does NOT mean here
- `exit_code=0` alone — floserv can exit 0 even when a solve diverged or produced no output
- The solve "ran without crashing" — crashing and not converging are different failure modes
- "stdout is non-empty" — a floserv startup banner is not a result
- `duration_s` was measured — timing alone proves nothing about result correctness

---

## Checklist 2 — Connectivity Test Completion

### ConnectionInfo Fields
- **[REQUIRED]** `conn.status == "ok"`
- **[REQUIRED]** `conn.version` is non-null and non-empty
- **[REQUIRED]** `conn.message` references the detected `flotherm.bat` path
- **[RECOMMENDED]** `conn.version` matches the version required by the project fixtures or workflow under test

### What "task complete" does NOT mean here
- Flotherm can be found — it also needs to be the correct version for the project being run

---

## General Rules

1. **Never claim complete based on exit_code alone.** Exit code 0 means floserv exited cleanly — it does not mean the thermal result is correct or even present.

2. **Always report duration_s.** This establishes a baseline. If a future run takes 10× longer, the agent should flag it.

3. **Always quote actual values.** "Temperature was extracted" is insufficient. "max_temp_C = 78.3, criterion < 85°C → PASS" is acceptable.

4. **stderr warnings ≠ failure, stderr ERRORs = investigate.** Floserv emits informational lines to stderr. Lines starting with `ERROR` or `FATAL` require investigation even if exit_code=0.
