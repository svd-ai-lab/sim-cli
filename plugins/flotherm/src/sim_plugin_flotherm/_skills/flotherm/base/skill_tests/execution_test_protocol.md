# Execution Test Protocol — flotherm-sim Phase A

> **Scope**: Tests requiring real Simcenter Flotherm 2504 installation.
> For structure tests (no Flotherm needed), see `tests/test_skill_structure.py`.

---

## Purpose

Structure tests (`test_skill_structure.py`) verify the agent's reference material is complete.
Execution tests verify the agent's workflow actually runs a real Flotherm project to completion.

A skill that passes structure tests can still fail execution tests if:
- The batch command is constructed incorrectly
- Environment variables (FLOUSERDIR, FLO_ROOT, etc.) are set wrongly
- floserv fails to find the project directory after extraction
- Output parsing fails on real floserv stdout

---

## Two Test Layers

| Layer | What it verifies | Pass condition |
|---|---|---|
| **Layer A — Execution Feasibility** | The driver runs floserv without crashing | `exit_code=0`, `duration_s>0`, `stdout` non-empty |
| **Layer B — Acceptance-Grounded Completion** | The agent correctly evaluates output against a criterion | Criterion value present and compared, PASS/FAIL reported |

Layer B requires Layer A to pass first.

---

## Pre-Test Checklist

Before running any execution test:

- [ ] `driver.connect().status == "ok"` (run smoke test first)
- [ ] `driver.connect().version == "2504"`
- [ ] `DEMO_PACK` exists at the expected path (see `conftest.py`)
- [ ] `driver.lint(DEMO_PACK).ok == True`
- [ ] Disk has at least 500 MB free (pack extraction + floserv temp files)

If any item fails: record as **pre-test blocker**. Do not run execution tests.

---

## Test Procedure

### Step 1 — Pre-flight
Run `TestPreFlight` class in `test_batch_execution.py`.
All tests must pass before proceeding.

### Step 2 — Input validation
Run `TestInputValidation` class.
These confirm detect/lint work on the real demo pack.

### Step 3 — Batch solve (marked `@slow`)
Run `TestBatchExecution` class with `pytest -m slow`.
Each test checks one aspect of RunResult.

### Step 4 — Output parsing
Run `TestOutputParsing` class (no Flotherm needed).
These test parse_output logic in isolation.

---

## Pass / Fail Criteria

### Layer A Pass

All of:
- [ ] `result.exit_code == 0`
- [ ] `result.duration_s > 0`
- [ ] `result.stdout` non-empty
- [ ] `result.solver == "flotherm"`
- [ ] No unhandled Python exception in `run_file`

### Layer B Pass

Layer A plus:
- [ ] `parse_output(result.stdout)` returns non-empty dict (if stdout contains JSON)
- [ ] OR: acceptance criterion confirmed against exit_code=0 + non-empty stdout if no JSON
- [ ] Actual values reported, not "see stdout"

---

## Failure Types

| Type | Description |
|---|---|
| `pre_test_blocker` | Environment not ready (Flotherm not installed, file not found) |
| `execution_failure` | `exit_code != 0` or Python exception in `run_file` |
| `output_failure` | stdout empty, stderr has ERROR lines |
| `parsing_failure` | `parse_output` returns {} when JSON was expected |
| `acceptance_failure` | Criterion not checked or misreported |

---

## Failure Log Template

```yaml
case_id: EX-XX
test_date: YYYY-MM-DD
pack_file: <path>
failure_layer: A | B | pre-test
failure_type: pre_test_blocker | execution_failure | output_failure | parsing_failure | acceptance_failure
observed_output:
  exit_code: <int>
  duration_s: <float>
  stdout_first_200: |
    <...>
  stderr: |
    <...>
expected_behavior: |
  <what the test protocol required>
suspected_root_cause: |
  <brief analysis>
fix_location:
  driver: sim/drivers/flotherm/driver.py  # if batch command or env setup wrong
  skill: skills/flotherm-sim/SKILL.md     # if agent protocol defect
  environment: <description>             # if pre-test blocker
```
