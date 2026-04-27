# Acceptance Checklists — fluent-sim v0

> These checklists define what "task complete" means for each workflow type.
> A task is complete when ALL applicable items pass — not when the last script exits 0.

---

## Pre-Execution Gate — Acceptance Criteria Must Be Defined

Before submitting the first `sim run` snippet, verify that **at least one outcome-based acceptance criterion** exists for this task.

An outcome-based criterion specifies what the simulation must produce or demonstrate — not just that it runs:

- ✅ "outlet average temperature between 28°C and 35°C"
- ✅ "150 iterations complete, then extract mass flow rate at outlet"
- ✅ "volume mesh generated with no negative volumes, cell count > 0"
- ❌ "跑完就好" — describes an operation, not an outcome
- ❌ "just run it" — same
- ❌ "run and see" — same

If no valid criterion exists, treat it as a missing Category A input (see SKILL.md §5.1) and ask the user before proceeding:
> "What result do you want to extract? How will you judge whether this simulation was successful?"

Do not proceed on the assumption that "successful execution = task complete."

---

## How to Use These Checklists

After the final step of a workflow, the agent must:

1. Run `sim query session.summary` and `sim query last.result`
2. Work through the relevant checklist below
3. Mark each item as PASS / FAIL / N/A with the actual observed value
4. If all REQUIRED items pass → report COMPLETE
5. If any REQUIRED item fails → report INCOMPLETE with specific failures

Checklist items marked **[REQUIRED]** must pass for any completion claim.
Items marked **[RECOMMENDED]** are best practice but may be waived with user consent.
Items marked **[OPTIONAL]** are only applicable if the user requested that output.

---

## Checklist 1 — Watertight Meshing Completion

### Session State
- **[REQUIRED]** `session.summary.connected = true`
- **[REQUIRED]** `session.summary.mode = "meshing"`
- **[REQUIRED]** `session.summary.run_count` = expected number of executed steps (verify against actual steps sent)

### Last Result
- **[REQUIRED]** `last.result.ok = true`
- **[REQUIRED]** `last.result.label = "switch-to-solver"` (if switch was requested) OR `"volume-mesh"` (if not)
- **[REQUIRED]** `last.result.result.volume_mesh_done = true`
- **[REQUIRED]** `last.result.result.workflow = "watertight-geometry"`

### Switch to Solver (if requested)
- **[REQUIRED if switch requested]** `last.result.result.switch_to_solver_done = true`
- **[RECOMMENDED]** `last.result.result.solver_type` is non-empty (confirms solver object was returned)

### Mesh Quality (observational)
- **[RECOMMENDED]** Cell count extracted from stdout of volume-mesh step and reported to user
- **[RECOMMENDED]** No negative volume warnings in mesh-check stdout
- **[OPTIONAL]** Surface mesh statistics (face count, min/max size)

### What "task complete" does NOT mean here:
- The workflow task list showed no errors (Fluent GUI task list is informational only)
- The Python snippet printed "OK"
- The process exited 0 without verifying `result` fields

---

## Checklist 2 — Fault-Tolerant Meshing Completion

### Session State
- **[REQUIRED]** `session.summary.connected = true`
- **[REQUIRED]** `session.summary.mode = "meshing"`
- **[REQUIRED]** `session.summary.run_count` matches expected step count

### Last Result
- **[REQUIRED]** `last.result.ok = true`
- **[REQUIRED]** `last.result.result.volume_mesh_done = true`
- **[REQUIRED]** `last.result.result.workflow = "fault-tolerant-meshing"`

### Known Version Compatibility
- **[REQUIRED]** No unhandled `LookupError` in any step's `stderr`
  (The `DefaultObjectSetting` issue is expected in some Fluent versions; it must be caught, not crash the step)

### Mesh Quality (observational)
- **[RECOMMENDED]** Total cell count extracted and reported
- **[RECOMMENDED]** No `negative volume` or `high skewness` warnings in stdout

---

## Checklist 3 — Solver Run Completion

### Session State
- **[REQUIRED]** `session.summary.connected = true`
- **[REQUIRED]** `session.summary.mode = "solver"`
- **[REQUIRED]** `session.summary.run_count = 3` (read-case-data + mesh-check + run-iterations)
  or higher if additional extraction steps were run

### Last Result (after iterations step)
- **[REQUIRED]** `last.result.ok = true`
- **[REQUIRED]** `last.result.result.iterations_run = N` (matches requested iteration count)
- **[REQUIRED]** `last.result.result.status = "complete"`

### Result Extraction (if requested)
- **[REQUIRED if extraction requested]** Extracted quantity present in `last.result.result` with a non-null value
- **[REQUIRED if extraction requested]** Quantity value is numeric or explicitly labeled as "see stdout" with stdout reproduced
- **[RECOMMENDED]** Report the sign convention (e.g., negative mass flow rate = outflow)

### Convergence (observational)
- **[OPTIONAL]** Residual values at final iteration extracted from stdout and reported
- **[OPTIONAL]** Confirm whether convergence was achieved (residuals below threshold) or only N iterations were run

### What "task complete" does NOT mean here:
- N iterations were scheduled (`iterate(iter_count=N)` was called)
- Fluent did not crash
- The `_result` dict was set

---

## Checklist 4 — Smoke / Connectivity Test Completion

### Session State
- **[REQUIRED]** `session.summary.connected = true` after connect
- **[REQUIRED]** `session.summary.run_count = 1` after smoke snippet

### Last Result
- **[REQUIRED]** `last.result.ok = true`
- **[REQUIRED]** `last.result.result.status = "ok"`

### Disconnect
- **[REQUIRED]** `sim disconnect` exits 0

### Log Files
- **[RECOMMENDED]** `.sim/v1_runs/` contains at least 1 JSON log file
- **[RECOMMENDED]** Log file `ok` field = true

---

## General Rules for Completion Claims

1. **Never claim complete based on exit code alone.** Exit code 0 means the CLI sent the snippet; it does not mean the simulation step produced correct results.

2. **Never claim complete based on print output alone.** `print("done")` in a snippet proves nothing about session state.

3. **Always quote the actual value** when reporting an extracted quantity. "Mass flow rate was computed" is insufficient; "mass flow rate = −0.0939 kg/s at outlet" is acceptable.

4. **Partial completion is a valid outcome.** If steps 1–5 passed and step 6 failed, report "5/6 steps completed; task incomplete due to [reason]". Do not claim full completion.

5. **run_count mismatch is a red flag.** If `run_count` is lower than expected, one or more steps silently did not execute. Investigate before claiming completion.
