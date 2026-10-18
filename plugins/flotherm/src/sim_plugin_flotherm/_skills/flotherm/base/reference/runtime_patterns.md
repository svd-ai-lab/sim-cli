# Runtime Control Patterns — flotherm-sim Phase A

> These are control patterns, not code templates.
> Phase A has no live session — all patterns describe the agent's decision logic around a single blocking `run_file` call.

---

## Pattern 0 — Phase A Execution Model

```
VALIDATE → RUN → EVALUATE → REPORT
```

Unlike Fluent (which has a live session), Flotherm Phase A is batch-only.
There is no `connect / exec / inspect / disconnect` lifecycle.
The entire solve is a single blocking call. The agent's decisions happen before and after.

---

## Pattern 1 — Validate Before Running

**When**: Before every `run_file` call.

**Actions**:
1. `driver.lint(pack_path)` → check ZIP structure, project directory present
2. `driver.connect()` → confirm Flotherm installed, get version
3. Confirm acceptance criterion exists (see SKILL.md §5)

**If any check fails**: Stop. Report the specific failure. Do not call `run_file`.

---

## Pattern 2 — Run and Capture

**When**: After all validation passes.

```python
result = driver.run_file(pack_path)
# result.exit_code, result.stdout, result.stderr, result.duration_s
```

This call blocks until floserv exits. It may take seconds to minutes.
Do not assume a timeout — floserv manages its own execution.

---

## Pattern 3 — Evaluate Output

**When**: After `run_file` returns.

```
result.exit_code?
  0  → check stderr for ERROR lines → check stdout non-empty → parse_output()
  ≠0 → STOP. Report exit_code + stderr. Task incomplete.
```

For structured data extraction:
```python
data = driver.parse_output(result.stdout)
# Returns last JSON object found in stdout, {} if none
```

---

## Pattern 4 — Failure Handling

**When**: Any check in Patterns 1–3 fails.

**Actions**:
1. Record which check failed (lint / connect / exit_code / stderr / acceptance)
2. Include relevant output:
   - lint failure → `lint_result.diagnostics`
   - connect failure → `conn.message`
   - exit_code failure → `result.exit_code` + `result.stderr[:500]`
   - acceptance failure → extracted value + criterion + FAIL
3. **Do not retry automatically.** Report to user with full context.

Retrying a failed solve without understanding why it failed wastes time. The agent's job is to surface the failure clearly so the user can decide.

---

## Pattern 5 — Report

**When**: At the end of every task (success or failure).

Always include:
- `exit_code`
- `duration_s`
- `stdout` summary (first and last 200 chars if long)
- `stderr` if non-empty
- Extracted values from `parse_output` (if any)
- Explicit PASS / FAIL against acceptance criterion

Format: structured, not narrative. Actual values must appear.

---

## Pattern 6 — Phase B/C Escalation

**When**: User asks for something Phase A cannot do.

Examples of Phase B/C requests:
- "Change the CPU power to 15W and re-run"
- "Run 5 variants with different airflow"
- "Show me the temperature at monitor point M1 after each iteration"

Response pattern:
> "This requires [Phase B FloSCRIPT authoring / Phase C live session], which is not yet implemented in the current driver. I can run the `.pack` as-is and report the batch result. Would you like to do that instead?"

Do not attempt to approximate Phase B/C behavior with Phase A tools.
