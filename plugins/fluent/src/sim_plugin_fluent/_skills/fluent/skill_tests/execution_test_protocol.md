# fluent-sim Execution Test Protocol

> **Scope**: Execution-grounded tests — requires real Fluent + sim installation.
> For natural-language behavioral tests (no Fluent required), see `nl_behavior_test_protocol.md`.
> For the execution test case dataset, see `execution_test_cases_v0.md`.

---

## Purpose

This protocol governs how execution-grounded tests are run, judged, and recorded for the `fluent-sim` skill.

Execution tests verify that:
- The skill's generated execution plan actually runs in a real Fluent session
- Each workflow step completes without exception
- Acceptance criteria are evaluated against real extracted values — not inferred from exit codes

**A skill that passes all behavioral tests can still fail execution tests.** Execution tests catch wrong API paths, incorrect zone names, missing extraction steps, and value-level errors that behavioral tests cannot surface.

---

## Relationship to Behavioral Tests

| Dimension | `nl_behavior_test_protocol.md` | This protocol |
|---|---|---|
| Fluent required | No | Yes |
| Catches | Planning defects, missing-input policy gaps | Implementation defects, API errors, extraction failures |
| Speed | Fast (seconds per case) | Slow (minutes per case, Fluent startup included) |
| Test cases | `nl_test_cases.md` (24 cases) | `execution_test_cases_v0.md` (EX-01–EX-05, subset) |
| Run when | Any time, CI-compatible | Only when Fluent environment available |

Neither replaces the other. Both must be maintained.

---

## Pre-Test Checklist

Before running any execution case, verify:

- [ ] `sim connect --mode solver --ui-mode no_gui --processors 2` returns `connected=true`
- [ ] `sim disconnect` cleanly exits after the above
- [ ] Required mesh/geometry file exists at the stated absolute path
- [ ] Boundary zone names have been confirmed (via diagnostic snippet or mesh inspection) — do **not** assume names from reference examples
- [ ] All Category A inputs for the case are confirmed (see `execution_test_cases_v0.md` §4 per-case requirements)
- [ ] Acceptance criteria are stated as outcome-based conditions before the test starts

If any check fails, record as a pre-test blocker in the failure log and do not start the case.

---

## Execution Paths

### Path R1 — Runtime v1 (preferred)

Incremental execution via `sim connect / run / query / disconnect`. Intermediate state is observable at every step.

```
sim connect --mode <meshing|solver> --ui-mode no_gui --processors <N>
sim query session.summary          # verify connected=true
sim run --code-file step_1.py --label <label>
sim query last.result              # verify ok=true before next step
  ... repeat for each step ...
sim run --code-file extract.py --label extract-<quantity>
sim query last.result              # verify extracted value present
sim disconnect
```

**When to use**: All EX cases by default. Required for Layer C (runtime feedback) tests.

**State recording**: Save raw JSON from every `sim query` call to `tests/execution/logs/<case_id>_step_<N>.json`.

### Path S0 — Script support v0 (cross-check / fallback)

Single-file execution via `sim run full_workflow.py --solver=fluent`. No intermediate state.

```
sim run full_workflow.py --solver=fluent
sim query last
```

**When to use**: Cross-check when Path R1 fails at an unexpected step. If the case passes on S0 but fails on R1, the defect is in the v1 runtime driver, not the workflow logic.

**Limitation**: Layer C (runtime feedback handling) cannot be tested on this path.

---

## Test Procedure

### Step 1 — Confirm pre-test checklist
See above. Do not skip.

### Step 2 — Give agent the natural-language prompt
Provide:
- The exact `prompt` from `execution_test_cases_v0.md` for the target case
- Access to the `fluent-sim` skill at `.claude/skills/fluent-sim/SKILL.md`
- Actual file paths on the test machine (substitute placeholder paths)

Do **not** provide:
- Hints about which step will work or fail
- The expected output values
- Which execution path to use (let the agent decide based on the skill)

### Step 3 — Verify pre-execution behavior
Before any `sim run` call, confirm the agent:
- Identified the correct workflow type (meshing / solver / full)
- Confirmed all Category A inputs (or asked for them and received answers)
- Stated acceptance criteria
- Did not infer meshing parameters or BC values from reference examples

If the agent proceeds to `sim connect` before confirming Category A inputs: record a `planning_failure` and stop the test.

### Step 4 — Execute via Path R1
Run each step. After each `sim run`:
- Save `sim query last.result` to log
- If `ok=false`: STOP. Record `execution_failure`. Do not continue to next step.
- Verify `run_count` in `session.summary` matches expected completed steps

### Step 5 — Evaluate acceptance criteria
After the final extraction step:
- Confirm the extracted value is present in `last.result.result` as a non-null numeric
- Compare against the stated acceptance criterion (range / threshold / presence)
- Record: actual value, criterion, PASS or FAIL

### Step 6 — Disconnect and finalize
```
sim disconnect
```
Record overall Layer A / Layer B / Layer C result.

---

## Pass/Fail Criteria

### Layer A — Execution Feasibility

PASS requires ALL of:
- [ ] Every `sim run` step returns `ok=true`
- [ ] `session.summary.run_count` matches expected step count
- [ ] No unhandled exceptions in any `stderr`
- [ ] `sim disconnect` exits 0

Exit code 0 alone does **not** constitute Layer A pass. `ok=true` per step is required.

### Layer B — Acceptance-Grounded Completion

PASS requires Layer A AND ALL of:
- [ ] Acceptance criterion quantity present in `last.result.result` as non-null numeric
- [ ] Quantity compared against criterion with explicit PASS/FAIL outcome
- [ ] Actual value reported (not "see stdout")

### Layer C — Runtime Feedback Handling

Applicable only when a deliberate failure or mid-execution query is part of the test design.

PASS requires:
- [ ] Agent reads `last.result` before deciding next action
- [ ] Agent halts on `ok=false` without proceeding
- [ ] Agent correctly infers progress from `run_count`
- [ ] Agent does not declare complete until all extraction + acceptance steps are done
- [ ] For failure cases: agent proposes the correct diagnostic action and waits for user input

---

## Failure Types

| Type | When it occurs | Primary fix location |
|---|---|---|
| `planning_failure` | Agent proceeds to execution with unconfirmed Category A inputs, or wrong workflow type | `SKILL.md` §4, `task_templates.md` |
| `execution_failure` | `ok=false` in any `sim run` step | Wrong API path → `reference/cheat_sheet.md` or example files; wrong zone name → diagnostic step needed |
| `runtime_state_failure` | `run_count` mismatch, unexpected session mode | `sim` v1 runtime driver |
| `extraction_failure` | Acceptance quantity absent or null in final result | Missing extraction step → `task_templates.md`; wrong report type → `reference/pyfluent_examples/` |
| `acceptance_failure` | Value present but not compared against criterion, or COMPLETE declared without checking | `SKILL.md` §4 Step 4, `acceptance_checklists.md` |
| `pre_test_blocker` | Environment not ready, file not found, pre-test checklist failed | Not a skill defect — resolve environment before re-running |

---

## Failure Log Template

```yaml
case_id: EX-XX
test_date: YYYY-MM-DD
natural_language_prompt: |
  <exact prompt provided>
execution_path: R1 | S0
failure_layer: A | B | C | pre-test
failure_type: planning_failure | execution_failure | runtime_state_failure | extraction_failure | acceptance_failure | pre_test_blocker
failed_at_step: <step label or number>
observed_output: |
  # sim query last.result at failure point:
  { ... }
expected_behavior: |
  <what the skill protocol required>
suspected_root_cause: |
  <brief analysis>
fix_location:
  skill: SKILL.md §X            # if skill protocol defect
  reference: reference/<file>   # if wrong API or template step
  runtime: sim v1 driver        # if session management defect
  environment: <description>    # if pre-test blocker
notes: |
  <additional context>
```

---

## First Batch Execution Order

Run in this order to maximize diagnostic value and minimize environment setup cost:

| Order | Case | Layer | Why this order |
|---|---|---|---|
| 1 | EX-01 | A | Validates the full v1 path works; all other cases blocked if this fails |
| 2 | EX-02 | B | Validates numeric acceptance evaluation; same mesh as EX-01, no new setup |
| 3 | EX-05 | B | Validates multi-field extraction completeness; same mesh, more extraction steps |

Run EX-03 (meshing) and EX-04 (deliberate failure) only after the first three pass. They require different setup (geometry file for EX-03; deliberate bad zone name injection for EX-04).
