# PyFluent Skill — Execution-Grounded Test Spec v0

> **Document type**: Execution test specification
> **Distinct from**: `.claude/skills/fluent-sim/tests/nl_test_cases.md` (behavioral/planning tests)
> **Status**: v0 — covers solver and meshing workflows; post-processing and DOE out of scope

---

## 1. Purpose

This document specifies **execution-grounded tests** for the `fluent-sim` skill.

The existing natural-language test dataset (`nl_test_cases.md`) validates *agent behavior*: whether the agent correctly identifies workflow type, detects missing inputs, routes to the right reference, and reasons about completion. Those tests are **planning-level**. An agent can pass all 24 of them without Fluent being installed.

This document tests something different:

> **Can the agent take a natural-language task, produce a concrete execution plan, and actually run it to completion in a real Fluent environment with verifiable output?**

Specifically, execution-grounded tests verify:

| Claim under test | What it requires |
|---|---|
| Skill produces an executable plan | Real Fluent must be called; the plan must not crash |
| Workflow steps advance correctly | Intermediate state must be observable via `sim query` |
| Acceptance criteria are checked on real results | Extracted values must be numeric and comparable |
| Runtime feedback handling is correct | Agent must respond to real `ok=false` or unexpected state, not simulated state |

**These tests do not replace behavioral tests.** They extend the test coverage to the execution layer. A skill that passes behavioral tests but fails execution tests has a code-generation or reference-accuracy defect, not a planning defect.

---

## 2. Test Scope

### In scope

- Cases where all Category A inputs are provided (complete-information cases)
- Cases that require a live Fluent process (meshing or solver)
- Cases where `sim` CLI commands (`connect`, `run`, `query`, `disconnect`) or `sim run script.py --solver=fluent` are the execution vehicle
- Cases where acceptance criteria produce a verifiable numeric or boolean output

### Out of scope

- Cases that test missing-input detection only (B-category and G-02) — no execution needed
- Cases that test contradiction handling (G-01) — no execution needed
- Cases that test v0 scope boundaries (C-01: post-processing) — execution would fail by design
- Post-processing, XY plots, graphics export — v0 limitation
- Parametric / DOE loops — v0 limitation

---

## 3. Test Layers

### Layer A — Execution Feasibility

**Goal**: Verify that the agent's generated plan actually runs without crashing.

**Pass condition**:
- Fluent process is started (via `sim connect` or `sim run script.py`)
- Every planned step completes without exception
- `sim query last.result` returns `ok=true` for each step
- Session reaches the expected terminal state

**This layer does not verify result correctness — only that execution completes.**

Typical failure modes caught here:
- Wrong API path in generated snippet
- Wrong zone name inferred from example instead of actual mesh
- Missing `import` or namespace error in snippet
- Fluent version incompatibility

---

### Layer B — Acceptance-Grounded Completion

**Goal**: Verify that the task's acceptance criteria are satisfied on real extracted values.

**Pass condition**:
- Layer A passes
- The acceptance criterion (numeric range, field presence, cell count) is actually checked
- The extracted value is reported as a concrete number
- Pass/fail against the criterion is determined from the real value, not from exit code

**This layer catches**: silently wrong results, converged-to-wrong-answer, unit errors, zone-name substitution errors that produce a value but the wrong one.

---

### Layer C — Runtime Feedback Handling

**Goal**: Verify that the agent correctly responds to real `sim query` output at mid-execution decision points.

**Pass condition**:
- Agent reads actual `session.summary` and `last.result` before each step
- Agent stops and escalates on `ok=false` (does not proceed to next step)
- Agent infers correct workflow progress from `run_count`
- Agent does not declare task complete until all acceptance criteria are verified

**This layer is only applicable when execution is performed incrementally (runtime v1 path).** It cannot be tested via the script support v0 path (single-file execution has no mid-step query points).

---

## 4. Candidate Executable Cases

The following cases from `nl_test_cases.md` are the best candidates for execution-grounded testing. Selection criteria: complete Category A inputs, verifiable acceptance criteria, minimal setup complexity.

---

### EX-01 — Solver feasibility baseline

**Source case**: A-02 (complete, English, explicit acceptance criteria)

**Why this first**: Provides the cleanest entry point — English prompt, all BCs stated, acceptance criteria explicit, mesh file path is a simple absolute path. Failure here indicates a fundamental execution path problem, not a content problem.

**Primary verification**: Layer A — does the agent's generated solver setup + 150-iteration plan actually run?

**Acceptance criterion**: `iterations_run = 150`, `outlet_avg_temperature` extractable as a numeric value.

**Preferred execution path**: Runtime v1 (`sim connect → sim run (stepwise) → sim query → sim disconnect`)

**Alternate path**: Script support v0 (`sim run full_workflow.py --solver=fluent`) — use as cross-check if v1 path fails mid-step.

**Required inputs** (must be confirmed before running):
- Mesh file: `/home/user/cases/mixing_elbow.msh.h5` (substitute actual path on test machine)
- Boundary zone names: must be queried from actual mesh, not assumed
- Processors: 2 (Category B default)

---

### EX-02 — Numerical acceptance criterion verification

**Source case**: A-03 (complete, modified BCs, 22–38°C range criterion)

**Why this second**: Extends EX-01 by requiring the extracted temperature to fall within a specific numeric range. Tests Layer B directly. The 22–38°C range is wide enough to be physically plausible, but requires a real extraction step — a missing or null value cannot satisfy it.

**Primary verification**: Layer B — does the extracted outlet mass-weighted average temperature actually fall within 22–38°C? Is the agent's final report a concrete number rather than "see stdout"?

**Acceptance criterion**: `outlet_mass_weighted_avg_temp` ∈ [22°C, 38°C] (real extracted value, not inferred).

**Preferred execution path**: Runtime v1

**Note**: This case uses modified BCs (cold inlet 0.6 m/s instead of 0.4 m/s). The temperature range may or may not hold depending on the actual mesh — the test is that the agent checks and reports the real value, not that the physics is correct.

---

### EX-03 — Meshing workflow feasibility

**Source case**: E-01 (geometry file, full workflow)

**Why this**: The only meshing case in the complete-information subset. Tests that the agent correctly:
1. Identifies meshing Category A inputs as required
2. Accepts user-provided meshing parameters
3. Runs the watertight geometry workflow to volume mesh completion

**Before running**: The agent must first ask for and receive meshing parameters (per Template 1). Once provided, this becomes a complete-information case eligible for execution. The test only begins after the agent has confirmed all meshing Category A inputs.

**Required inputs to provide for test execution**:
- Geometry file: must be an actual `.pmdb` file on the test machine
- Length unit: `mm` or `m` (provide actual value)
- Max surface mesh size: e.g., `5` (in chosen unit)
- Volume fill: `poly-hexcore`
- Max hex cell length: e.g., `2` (in chosen unit)
- Switch to solver: yes

**Primary verification**: Layer A — `volume_mesh_done = true` in `last.result.result` after volume mesh step. Cell count > 0 extracted from stdout.

**Preferred execution path**: Runtime v1 (meshing mode)

---

### EX-04 — Runtime feedback: real failure handling

**Source case**: Derived from D-01 (boundary zone name mismatch)

**Purpose**: Deliberately trigger a real `ok=false` result by using a wrong boundary zone name in the setup-bc step. Verify the agent stops, reads `last.result.stderr`, identifies the root cause, and asks the user for the correct zone name — rather than retrying or guessing.

**How to create the failure**: After mesh is loaded, inject an intentionally wrong zone name (e.g., `"cold-inlet"` when the actual name is `"velocity_inlet_cold"` or similar).

**Primary verification**: Layer C — does the agent halt on `ok=false`, correctly identify `LookupError` in stderr, propose the diagnostic snippet (`list(solver.settings.setup.boundary_conditions.velocity_inlet.keys())`), and wait for user input?

**Preferred execution path**: Runtime v1 (failure is observable only step-by-step)

**This case has no pass condition for the simulation itself** — pass is defined by correct agent behavior after the failure, not by the simulation completing.

---

### EX-05 — Multi-field extraction with output format requirement

**Source case**: G-03 (complete, three output fields required in JSON)

**Why this**: Tests whether the agent correctly treats explicit output format requirements as part of the acceptance definition. Requires three separate extraction steps (outlet temperature, cold/hot inlet mass flow rates, final residuals). A plan that only extracts one value fails Layer B.

**Primary verification**: Layer B — `last.result.result` contains all four fields: `outlet_temp_celsius`, `cold_inlet_mfr`, `hot_inlet_mfr`, `final_residuals`. Each field is non-null and numeric.

**Preferred execution path**: Runtime v1

**Required inputs**: Correct absolute path to `mixing_elbow.msh.h5` on test machine. (The `E:\data\` path in the original prompt does not exist — substitute the actual path before running.)

---

## 5. Required Environment

All execution tests require the following to be present and functional:

| Component | Requirement | Notes |
|---|---|---|
| Ansys Fluent | Installed and licensed | Version 2024 R1 or later recommended for PyFluent v0.38.0 compatibility |
| PyFluent | `pip install ansys-fluent-core` | v0.38.0; `import ansys.fluent.core as pyfluent` must succeed |
| sim CLI | clone `svd-ai-lab/sim-cli` and `pip install -e ".[pyfluent]"` | `sim connect --mode solver` must succeed |
| sim v1 runtime driver | Implemented per `specs/pyfluent_runtime_driver_v1.md` | Required for runtime v1 path |
| Mesh/geometry files | See per-case requirements in §4 | Absolute paths must be confirmed before test starts |
| Platform | Windows (PowerShell) or Linux (bash) | Path separators differ; confirm before running |
| GUI mode | `--ui-mode no_gui` for automated tests | Use `--ui-mode gui` only for manual visual verification |
| Processors | `--processors 2` (default) | Adjust if machine has fewer cores |

**File sourcing**:
- The mixing elbow mesh (`mixing_elbow.msh.h5`) can be obtained via PyFluent's built-in example downloader: `pyfluent.download_file("mixing_elbow.msh.h5", "examples")` — requires network access
- Geometry files (`.pmdb`) for meshing tests must be sourced separately; PyFluent examples include `mixing_elbow.pmdb` via the same downloader

---

## 6. Test Procedure

### 6.1 Pre-execution gate (applies to all cases)

Before starting any test:

1. Confirm all Category A inputs are provided (or will be provided as part of the test setup).
2. Confirm acceptance criteria are stated as outcome-based conditions, not operational ones.
3. Confirm the required files exist at the stated paths on the test machine.
4. Confirm `sim connect --mode solver --ui-mode no_gui --processors 2` returns `connected=true` in a smoke test.

If any of these checks fail, the test cannot start. Record the blocker in the failure log (§8).

---

### 6.2 Execution path A — Runtime v1 (preferred)

This path tests incremental execution with observable intermediate state.

```
Step 1:  sim connect --mode <meshing|solver> --ui-mode no_gui --processors 2
Step 2:  sim query session.summary  →  verify connected=true, mode correct
Step 3:  sim run --code-file step_N.py --label <label>
Step 4:  sim query last.result  →  verify ok=true before Step 5
         If ok=false: STOP. Record failure. Do not proceed.
Step 5:  Repeat Steps 3–4 for each planned step
Step 6:  sim query session.summary  →  verify run_count matches expected
Step 7:  Run acceptance extraction step (if required)
Step 8:  sim query last.result  →  verify extracted value present and numeric
Step 9:  sim disconnect
Step 10: Evaluate acceptance criteria against extracted value
         Report: PASS / FAIL with actual value and criterion
```

**Intermediate state recording**: After each `sim query`, save the raw JSON to a log file (e.g., `test_EX-01_run_N.json`). These are required for failure diagnosis.

**When to use v1**: All EX cases except when a v0 cross-check is specifically requested.

---

### 6.3 Execution path B — Script support v0 (cross-check / fallback)

This path runs the entire workflow as a single script. No intermediate state is observable.

```
Step 1:  Write full workflow script (no launch_fluent(); solver injected or launched in script body for v0)
Step 2:  sim run full_workflow.py --solver=fluent
Step 3:  sim query last  →  inspect stored JSON result
Step 4:  Verify last.result contains expected output fields
Step 5:  Evaluate acceptance criteria
```

**Limitations**:
- Layer C (runtime feedback handling) cannot be tested on this path — there are no mid-step query points.
- A failure surfaces only at script end; root cause may be hard to isolate.
- Use as cross-check when v1 path fails at an unexpected step and you need to determine whether the failure is in the v1 runtime or in the workflow logic itself.

**When to use v0**: Cross-checking EX-01 or EX-02 if v1 produces unexpected behavior; also as the baseline for any case where v1 driver is not yet deployed.

---

### 6.4 Distinguishing v0 and v1 failures

If the same case passes on v0 but fails on v1, the defect is in the v1 runtime driver (session management, snippet injection, state serialization), not in the skill or workflow logic.

If the case fails on both, the defect is in the workflow logic (wrong API path, wrong zone name, missing step), which is a skill or reference defect.

---

## 7. Pass/Fail Criteria

### Pass — Layer A (Execution Feasibility)

All of the following must be true:

- [ ] `sim connect` returns `connected=true` with correct mode
- [ ] Every `sim run` step returns `ok=true` in `last.result`
- [ ] `session.summary.run_count` matches the number of steps sent
- [ ] No unhandled exceptions in any step's `stderr`
- [ ] `sim disconnect` exits 0

Exit code 0 alone does **not** constitute a pass. `ok=true` in `last.result` is required for each step.

### Pass — Layer B (Acceptance-Grounded Completion)

All Layer A conditions plus:

- [ ] The acceptance criterion quantity is present in `last.result.result` as a non-null, numeric value
- [ ] The value is compared against the stated criterion (range, threshold, or exact match)
- [ ] The comparison result is explicitly reported: PASS or FAIL with the actual value

"See stdout" is not an acceptable reporting format. The value must appear in the structured result.

### Pass — Layer C (Runtime Feedback Handling)

- [ ] Agent reads `last.result` before deciding the next step
- [ ] Agent halts on `ok=false` without proceeding to the next step
- [ ] Agent correctly infers completed steps from `run_count`
- [ ] Agent does not declare task complete until acceptance criteria are verified
- [ ] For failure cases (EX-04): agent proposes the correct diagnostic action and waits

---

### Failure Types

| Type | Description | Typical cause |
|---|---|---|
| `planning_failure` | Generated plan is structurally wrong (wrong step order, wrong mode) | Skill template defect |
| `execution_failure` | A step crashes with exception or `ok=false` | Wrong API path, wrong zone name, version incompatibility |
| `runtime_state_failure` | `run_count` mismatch, session in unexpected mode | v1 driver defect or race condition |
| `extraction_failure` | Acceptance criterion quantity not present or null in result | Missing extraction step, wrong report type |
| `acceptance_failure` | Extracted value present but criterion not checked or misreported | Agent declared complete without comparing value |

---

## 8. Failure Logging Template

```yaml
case_id: EX-XX
natural_language_prompt: |
  <exact prompt given to agent>
generated_plan_summary: |
  <brief description of the plan the agent produced>
execution_path: runtime_v1 | script_v0
failure_layer: A | B | C
failure_type: planning_failure | execution_failure | runtime_state_failure | extraction_failure | acceptance_failure
failed_at_step: <step label or step number>
observed_output: |
  # sim query last.result at failure point:
  {
    "ok": ...,
    "label": "...",
    "stderr": "...",
    "stdout": "..."
  }
expected_behavior: |
  <what should have happened>
suspected_root_cause: |
  <brief analysis>
fix_location:
  skill: SKILL.md §X — <description>       # if skill protocol defect
  reference: reference/<file>.md            # if wrong API example or wrong template step
  runtime: sim v1 driver                    # if session management defect
  sim_cli: sim connect/run/query/disconnect # if CLI interface defect
notes: |
  <any additional context>
```

---

## 9. Relationship to Existing Skill Tests

| Dimension | `nl_test_cases.md` (behavioral) | This document (execution-grounded) |
|---|---|---|
| What is tested | Agent planning and reasoning | Agent output actually running in Fluent |
| Fluent required | No | Yes |
| sim required | No | Yes |
| Pass criterion | Agent asks the right questions / forms the right plan | Real workflow completes, real values extracted |
| Catches | Missing-input failures, wrong workflow classification, premature completion claims | Wrong API paths, zone name errors, missing extraction steps, value outside criterion |
| When to run | Any environment, no solver needed | Only when Fluent + sim are available |
| Replaces the other | No | No |

**Both test layers must be maintained.** Behavioral tests are fast, environment-independent, and catch planning defects early. Execution tests are slow, environment-dependent, and catch implementation correctness. Replacing either with the other produces blind spots.

A skill that passes behavioral tests but fails execution tests has correct reasoning with incorrect implementation details (wrong API, missing step, wrong field name). A skill that passes execution tests but skips behavioral tests may work on the tested cases but fail on new inputs due to undetected missing-input policy gaps.

---

## 10. Recommended First Batch

Run these three to five cases first, in this order:

### Batch 1: Smoke + Solver Feasibility

**EX-01** (Layer A, runtime v1)

- Why first: Establishes whether the full v1 execution path works at all. If this fails, all other cases are blocked until the v1 driver issue is resolved.
- Primary check: Does `sim connect → setup → iterate → extract → disconnect` complete without error?
- Path: Runtime v1

**EX-02** (Layer B, runtime v1)

- Why second: Immediately after EX-01 confirms the path works, test that numeric acceptance criteria are actually evaluated (not just that execution completes).
- Primary check: Is the extracted temperature a real number? Is it compared against 22–38°C?
- Path: Runtime v1

### Batch 2: Extraction Completeness

**EX-05** (Layer B, runtime v1)

- Why: Tests multi-field extraction. A plan that extracts only one of three required values fails Layer B even if execution succeeds. This is the most common "extraction_failure" pattern.
- Primary check: All four JSON fields (`outlet_temp_celsius`, `cold_inlet_mfr`, `hot_inlet_mfr`, `final_residuals`) present and numeric.
- Path: Runtime v1

### Batch 3 (if Batch 1+2 pass): Meshing and Failure Handling

**EX-03** (Layer A, runtime v1, meshing mode)

- Why: Meshing workflow has not been execution-tested at all. The skill's Template 1 step sequence needs real-world validation.
- Primary check: `volume_mesh_done = true`, cell count > 0 in stdout.
- Path: Runtime v1 (meshing mode)

**EX-04** (Layer C, runtime v1)

- Why: Real failure handling has not been tested under real Fluent conditions. Simulated state (D-category nl_test cases) is not sufficient to confirm the agent stops correctly when Fluent itself throws a `LookupError`.
- Primary check: Agent stops on real `ok=false`, proposes zone name diagnostic snippet, does not retry.
- Path: Runtime v1 (failure is only observable incrementally)

---

## Appendix: Suggested Companion Files

The following files are not part of this spec but are recommended for Batch 1 execution:

| File | Purpose |
|---|---|
| `tests/execution/pyfluent_execution_cases_v0.md` | Detailed per-case inputs, expected outputs, and criterion values for EX-01~05 |
| `scripts/runtime_v1_smoke.ps1` | PowerShell script for running the smoke test (sim connect + trivial snippet + disconnect) |
| `scripts/runtime_v1_solver_ex01.ps1` | Step-by-step sim commands for EX-01 (generated after plan is confirmed) |
| `scripts/runtime_v1_meshing_ex03.ps1` | Step-by-step sim commands for EX-03 |

These scripts should be generated by the agent after the execution plan is confirmed by the user — they are not authored in advance.
