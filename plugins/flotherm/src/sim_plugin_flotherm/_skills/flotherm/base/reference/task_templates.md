# Task Templates — flotherm-sim Phase A

> Each template defines: goal, required inputs, step order, and completion condition.
> Phase A only. For Phase B (FloSCRIPT authoring) and Phase C (live session), see future versions.

---

## Template 1 — Batch Solve (.pack project)

### Goal
Run an existing Flotherm `.pack` project in batch mode via `floserv.exe -b` and verify the result.

### Required Inputs

| Input | Type | Must confirm if missing |
|---|---|---|
| `.pack` file path | Absolute path to `.pack` ZIP | YES |
| Acceptance criterion | e.g. "exit_code=0" or "max temperature < 85°C" | YES — defines what success means |

### Common Missing Items
- Acceptance criterion (users often say "just run it" — this is not an outcome criterion)
- Correct absolute path (relative paths will fail when extracted to a temp directory)

### Runtime Step Order

| Step | Action | Notes |
|---|---|---|
| 1 | `driver.lint(pack_path)` | Validate ZIP structure and project directory |
| 2 | `driver.connect()` | Confirm Flotherm 2504 installed and detectable |
| 3 | `driver.run_file(pack_path)` | Blocking batch solve — may take seconds to minutes |
| 4 | `driver.parse_output(result.stdout)` | Extract structured data if present |
| 5 | Evaluate acceptance criterion | Compare against extracted values or exit_code |

### Completion Condition
- `result.exit_code == 0`
- `result.stderr` contains no ERROR/FATAL lines
- `result.stdout` is non-empty
- If acceptance criterion requires a specific value: that value is present in `parse_output()` result AND compared against the criterion
- `result.duration_s` measured and reported

**"exit_code=0 alone" is NOT sufficient to declare task complete** if the user specified an output-based criterion.

---

## Template 2 — Smoke / Connectivity Test

### Goal
Verify that Simcenter Flotherm is installed and the driver can detect it. Does not run a simulation.

### Required Inputs
None required from user. All checks are automatic.

### Runtime Step Order

| Step | Action | Notes |
|---|---|---|
| 1 | `driver.connect()` | Check installation detectable |
| 2 | Inspect `ConnectionInfo` | Verify `status="ok"`, `version="2504"` |
| 3 | `driver.lint(any_pack)` (optional) | Validate a known-good .pack if available |

### Completion Condition
- `conn.status == "ok"`
- `conn.version` is non-null
- `conn.message` contains the detected path to `flotherm.bat`

### When to Use
- Before attempting any batch solve
- When diagnosing "Flotherm not found" errors
- As a pre-test gate before any execution test

---

## Notes on Template Selection

- If the user says "run my simulation", confirm: do they have a `.pack` file? → Template 1.
- If the user says "check if Flotherm is installed" → Template 2.
- If the user says "change the power value and re-run" → Phase B (not yet implemented, explain scope boundary).
- **Never assume acceptance criteria.** "Run and see what happens" does not constitute an outcome criterion. Ask: "What result do you want to verify? How will you judge whether the simulation succeeded?"
