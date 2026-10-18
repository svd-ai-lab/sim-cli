---
name: starccm-sim
description: Use when driving Simcenter STAR-CCM+ for CFD/multiphysics tasks — batch macro execution, mesh generation, solver setup, result extraction. Covers Java macro API, batch CLI, and common workflow patterns.
---

# starccm-sim

Skill for controlling **Simcenter STAR-CCM+** through `sim-cli`.

---

## First principles

1. **Star-CCM+ uses Java macros, not Python scripts.** Every automation script is a `.java` file extending `StarMacro`. There is no pip-installable Python SDK.
2. **Execution is batch-mode subprocess.** `starccm+ -batch macro.java [case.sim]` — sim never imports Star-CCM+ libraries.
3. **The macro recorder is your best API discovery tool.** Record GUI actions → read generated `.java` → adapt.
4. **License is required.** `CDLMD_LICENSE_FILE` must point to a valid license file. The driver auto-detects `license.dat` near the installation.

---

## Hard constraints

- **Script format**: `.java` files only. Must `extends StarMacro` and `import star.common.*`.
- **Output convention**: Print a JSON object via `sim.println(jsonString)` as the last meaningful output line. The driver's `parse_output()` extracts it.
- **No persistent session**: Current driver is one-shot only (`supports_session = False`). Each `sim run` starts and stops Star-CCM+.
- **Startup overhead**: ~15-20s per run (JVM + license checkout). Plan macros to do meaningful work per invocation.

---

## File index

| Path | What it contains | When to read |
|------|-----------------|--------------|
| `base/reference/java_macro_api.md` | Java macro API reference — classes, methods, patterns | When writing any macro |
| `base/reference/batch_execution.md` | CLI flags, license setup, parallel execution | When configuring runs |
| `base/snippets/starccm_01_smoke_test.java` | Minimal connectivity test | First run verification |
| `base/snippets/starccm_02_pipe_flow.java` | Geometry creation + volume mesh generation | E2E reference |
| `base/known_issues.md` | Vendor quirks and workarounds | When debugging failures |
| `solver/21.02/notes.md` | Version-specific notes for 2602 (21.02) | After version detection |

---

## Required protocol

1. **Verify installation**: `sim check starccm` — confirms binary found + license accessible.
2. **Write macro**: `.java` file extending `StarMacro`. End with `sim.println(json)`.
3. **Lint**: `sim lint macro.java` — checks structure before execution.
4. **Run**: `sim run macro.java --solver starccm` — executes in batch mode.
5. **Check result**: `sim logs last` — verify `exit_code == 0` AND parsed output meets acceptance criteria.

---

## Input classification

- **Category A (must ask user)**: Geometry file path, physics models, boundary condition values, acceptance criteria.
- **Category B (may default)**: Processor count (`-np`), mesh base size, iteration count.
- **Category C (derive from context)**: Region names, boundary names, field function names — discover via macro recorder or inspection macro.
