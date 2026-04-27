# fluent-sim Natural-Language Behavior Test Protocol

> **Scope**: Natural-language / behavioral tests only. For execution-grounded tests (real Fluent required), see `execution_test_protocol.md` and `execution_test_cases_v0.md`.

## Purpose

This document defines how to test whether the `fluent-sim` skill correctly shapes **agent behavior** in response to natural-language task prompts.

The goal is not to check whether the agent can explain the skill.
The goal is to check whether the skill changes agent behavior in realistic Fluent task scenarios — without requiring a real Fluent installation.

**This protocol covers Intent 1 (trigger detection) and Intent 2 (content/behavior tests). It does not test whether generated plans actually execute correctly in Fluent.**

The skill should be evaluated on:
1. task understanding
2. missing-input detection
3. reference routing
4. runtime-control awareness
5. workflow classification
6. acceptance-aware completion

---

## Core Principle

A skill is effective only if it works under **low-context, black-box conditions**.

Therefore, skill testing should avoid contamination from prior conversation context.

The preferred test mode is:
- use a fresh subagent or isolated context
- provide only:
  - the skill
  - its reference files
  - one natural-language test case
- do not explain what capability is being tested
- do not reveal the expected answer in advance

---

## Recommended Test Modes

### Mode A — Black-box test (primary)
Use a fresh subagent or isolated context.

Provide:
- the `fluent-sim` skill
- reference files
- one natural-language test case

Observe:
- whether the skill is triggered
- whether the agent asks for missing critical information
- whether the agent chooses the right reference source
- whether the agent treats the task as runtime control instead of only script generation
- whether the agent uses acceptance criteria correctly

This is the main validity test.

### Mode B — White-box debug (secondary)
Use after a failure in black-box testing.

Ask:
- why the skill was or was not triggered
- why a clarification question was or was not asked
- why a specific reference was used
- why the task was classified as meshing / solver / full workflow / post
- why the agent decided the task was complete

This mode is only for diagnosis and refinement.

---

## Subagent Execution

Subagents dispatched via the `Agent` tool are the preferred execution vehicle because they provide genuine context isolation — no shared conversation history, no prior hints.

However, two fundamentally different test intents exist when using subagents. These must not be mixed.

### Intent 1 — Trigger test

**Purpose**: Does the skill's `description` field cause the agent to load and apply the skill without being told to?

**Subagent prompt construction**:
- Provide only the natural-language test case prompt (the `prompt` field from `nl_test_cases.md`)
- Do NOT mention "fluent-sim skill" or "use the skill"
- Do NOT describe what capability is under test
- DO ensure the subagent has file-system access to the skill directory

**What this tests**: Whether the `description` field in `SKILL.md` frontmatter is specific enough to be matched.

**Failure interpretation**: If the subagent does not use the skill → fix the `description` field, not the test.

### Intent 2 — Content test

**Purpose**: Assuming the skill is loaded, does the skill content actually guide the agent to the correct behavior?

**Subagent prompt construction**:
- Explicitly tell the subagent: "You are working on a Fluent simulation task. Use the fluent-sim skill located at `.claude/skills/fluent-sim/SKILL.md` and its reference files."
- Then provide the test case prompt

**What this tests**: Whether the skill's protocols, reference routing rules, missing-input policy, and acceptance criteria are clear enough to produce the correct behavior.

**Failure interpretation**: If the subagent uses the skill but still fails → fix the relevant skill document (see Failure-to-Fix Mapping).

### Which test to run

Run **Intent 2 first**. If skill content is wrong, there is no point testing trigger quality.
Only run **Intent 1** after skill content is validated.

### Result collection

Subagents return a single message to the parent. The parent agent must:
1. Record the subagent's full response
2. Compare it against `expected_skill_behavior` from the corresponding test case
3. Assign a pass/fail judgment per capability dimension (not a single overall pass/fail)
4. Log failures using the Failure Logging Format defined below

The parent agent performs the judgment. Human review is recommended for ambiguous cases, particularly G-02 (boundary case: "don't ask me, just default") and D-type runtime feedback cases.

---

## Test Execution Procedure

For each test case, follow this sequence.

### Step 1 — Create isolated test context
Prefer a fresh subagent or fresh conversation context.

### Step 2 — Give only the required inputs
Provide:
- the natural-language test case
- access to the `fluent-sim` skill and its reference files

Do not provide:
- hints about what is missing
- hints about which reference should be used
- hints about whether the case is complete or incomplete
- hints about the expected behavior

### Step 3 — Capture first-pass behavior
Record:
- whether the skill appears to trigger
- whether the agent asks clarification questions
- whether it chooses runtime or single-script planning
- whether it cites or consults the correct reference type
- whether it identifies workflow type correctly
- whether it uses acceptance criteria in its reasoning

For **Category D (Runtime Feedback) cases**, additionally record:
- whether the agent reads the `current_state` field before deciding next action
- whether the agent stops execution when `ok=false` (D-01)
- whether the agent correctly infers workflow progress from `run_count` (D-02)
- whether the agent distinguishes partial step success from overall task completion (D-03, D-04)
- whether the agent avoids resuming blindly without verifying the current state

### Step 4 — Judge result
Judge the response against the expected behavior of the case.

### Step 5 — If needed, run white-box diagnosis
If the first-pass behavior is wrong or incomplete, ask the agent to explain:
- why it made that decision
- why it did not ask for clarification
- why it selected that reference
- why it considered the task complete

### Step 6 — Map failure to skill defect
Do not patch the test prompt first.
First determine whether the failure comes from:
- trigger condition weakness
- skill scope ambiguity
- missing-input policy not clear enough
- runtime-control policy not clear enough
- acceptance policy not clear enough
- reference routing rules not clear enough

---

## Pass/Fail Criteria by Capability

### 1. Task Understanding
Pass if the agent:
- identifies the intended workflow type correctly
- distinguishes solver / meshing / full workflow / post-processing
- does not confuse sim runtime tasks with standalone script generation

Fail if the agent:
- chooses the wrong workflow class
- assumes a script-only plan when runtime control is required
- misses the task objective

Likely fix location:
- `SKILL.md` → task scope / when to use / workflow recognition guidance
- `reference/task_templates.md`

---

### 2. Missing-input Detection
Pass if the agent:
- asks for missing critical simulation inputs before execution planning
- does not silently assume key physics, BCs, or acceptance criteria

Fail if the agent:
- fills in critical values without asking
- ignores ambiguity
- asks too little or asks after it has already started planning execution

Likely fix location:
- `SKILL.md` → Missing-input policy
- `reference/task_templates.md`
- `reference/acceptance_checklists.md`

---

### 3. Reference Routing
Pass if the agent:
- chooses the right reference type for the problem
- uses examples for example-shaped tasks
- uses runtime patterns for runtime control decisions
- uses acceptance checklists for completion decisions

Fail if the agent:
- always uses examples
- never uses references
- chooses the wrong reference family

Likely fix location:
- `SKILL.md` → Required references / when to consult what
- `reference/runtime_patterns.md`
- `reference/task_templates.md`
- `reference/acceptance_checklists.md`

---

### 4. Runtime-Control Awareness
Pass if the agent:
- treats iterative simulation work as a runtime control problem when appropriate
- proposes a stepwise plan such as connect → run snippet → query → continue
- does not always collapse everything into one full script

Fail if the agent:
- always proposes one-shot scripts
- ignores runtime state and intermediate feedback
- cannot explain how to continue after a partial result

Likely fix location:
- `SKILL.md` → Runtime control policy
- `reference/runtime_patterns.md`

---

### 5. Workflow Classification
Pass if the agent:
- correctly decides whether the task is meshing, solver, post, or full workflow
- uses file type and user goal to infer stage correctly

Fail if the agent:
- treats geometry input as solver-ready
- treats finished case/data as if meshing is still required
- fails to distinguish runtime post-processing from solve/mesh setup

Likely fix location:
- `SKILL.md` → task classification guidance
- `reference/task_templates.md`

---

### 6. Acceptance-Aware Completion
Pass if the agent:
- distinguishes "script ran" from "task completed"
- checks user-defined or task-defined completion criteria
- does not declare success prematurely

Fail if the agent:
- stops when execution succeeds, even if acceptance criteria are unmet
- ignores requested output artifacts
- does not ask for missing completion criteria

Likely fix location:
- `SKILL.md` → Acceptance policy
- `reference/acceptance_checklists.md`

---

## Failure Logging Format

For each failed case, record:

- `case_id`
- `observed_behavior`
- `expected_behavior`
- `failure_type`
  - trigger_failure
  - missing_input_failure
  - reference_routing_failure
  - runtime_awareness_failure
  - runtime_feedback_failure
  - workflow_classification_failure
  - acceptance_failure
  - contradiction_failure
- `suspected_skill_location`
- `suggested_fix`

---

## Failure-to-Fix Mapping

### Trigger failure
Symptoms:
- skill not used when it should be
Likely cause:
- frontmatter `description` too vague or too narrow
Fix:
- revise trigger conditions in `SKILL.md`

### Over-triggering
Symptoms:
- skill used when a simpler/general skill should be enough
Likely cause:
- `description` too broad
Fix:
- narrow usage conditions in `SKILL.md`

### Missing-input failure
Symptoms:
- agent silently assumes BCs / physics / acceptance criteria
Fix:
- strengthen missing-input policy in `SKILL.md`
- add explicit examples in `task_templates.md`

### Reference-routing failure
Symptoms:
- wrong reference source used
Fix:
- make reference-selection guidance explicit in `SKILL.md`
- add "when to consult this file" headers in reference docs

### Runtime-awareness failure
Symptoms:
- agent always writes one big script
Fix:
- strengthen runtime control policy
- add more explicit connect/run/query loop patterns

### Workflow-classification failure
Symptoms:
- wrong stage selected
Fix:
- add clearer stage inference rules in `task_templates.md`

### Runtime-feedback failure
Symptoms:
- agent resumes execution without reading `current_state`
- agent ignores `ok=false` and continues to next step
- agent treats partial step success as overall task completion
- agent cannot infer progress from `run_count`
Fix:
- add explicit "read state before acting" rule to `SKILL.md` §4 (Agent Workflow)
- strengthen Pattern 2 (execution loop) and Pattern 5 (failure handling) in `runtime_patterns.md`

### Contradiction failure
Symptoms:
- agent mechanically executes contradictory inputs without flagging conflict
- agent silently discards one of the conflicting conditions
Fix:
- add contradiction detection to `SKILL.md` §5 (Missing Input Policy) as a parallel concern
- add note to `task_templates.md` that conflicting BCs are a variant of "ambiguous input"

### Acceptance failure
Symptoms:
- task declared complete too early
Fix:
- strengthen acceptance policy
- expand `acceptance_checklists.md`

---

## General Refinement Rule

When a test fails:
1. do not first patch the case prompt
2. identify which capability failed
3. map the failure to the relevant skill document
4. revise the skill
5. retest in a fresh isolated context

---

## Minimum Quality Bar for v0

The skill may be considered a usable v0 only if it consistently demonstrates:

- correct task classification on common cases
- reliable missing-input detection
- sensible reference routing
- basic runtime-control awareness
- acceptance-aware completion behavior

If any of these repeatedly fail, the skill is not yet strong enough for reliable runtime-guided simulation work.

---

## Scope Note

This protocol tests the skill as a **behavior-shaping artifact**.

It does not test:
- actual simulation correctness
- PyFluent runtime implementation details
- Fluent numerical quality
- mesh quality thresholds themselves

Those belong to workflow/runtime validation, not skill validation.