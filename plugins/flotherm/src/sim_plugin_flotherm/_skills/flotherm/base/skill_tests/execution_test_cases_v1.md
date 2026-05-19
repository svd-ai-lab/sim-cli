# Execution Test Cases v1 — flotherm-sim

> **Status**: v1 — covers all testable driver operations.
> Replaces v0 which assumed batch `-b` mode works (it does not in Flotherm 2504).

---

## Test Oracles

| ID | File | Type | Location |
|----|------|------|----------|
| PACK-1 | Mobile_Demo-Steady_State.pack | PCB steady-state thermal | `examples/FloSCRIPT/Demonstration Examples/Transient Power Update/` |
| PACK-2 | SuperPosition.pack | Superposition example (has ccstatefile.txt) | `examples/Demonstration Models/Superposition/` |
| XML-1 | Grid-HeatSinks-and-Fans.xml | FloSCRIPT utility (no solve command) | `examples/FloSCRIPT/Utilities/` |
| XML-2 | Make_Tube.xml | FloSCRIPT demo (no solve command) | `examples/FloSCRIPT/Demonstration Examples/Voxelization/` |

All files ship with Simcenter Flotherm 2504 at:
```
E:\Program Files (x86)\Siemens\SimcenterFlotherm\2504\examples\
```

---

## EX-01 — Connectivity Check (Layer A)

**Goal**: Verify `driver.connect()` detects Flotherm 2504 installation.

**Acceptance criteria**:
| Field | Expected |
|-------|----------|
| `status` | `"ok"` |
| `version` | `"2504"` |
| `message` | contains `"flotherm.bat"` |

**Why first**: All other tests depend on Flotherm being detected.

---

## EX-02 — Lint .pack Files (Layer A)

**Goal**: Verify `driver.lint()` validates .pack structure.

**Test matrix**:
| Input | Expected `ok` | Notes |
|-------|---------------|-------|
| PACK-1 (Mobile_Demo) | `True` | Valid ZIP, has project directory |
| PACK-2 (SuperPosition) | `True` | Valid ZIP, has project directory + ccstatefile |
| Nonexistent file | `False` | Diagnostic: "Cannot read file" |
| Empty file | `False` | Diagnostic: "Pack file is empty" |

---

## EX-03 — Lint FloSCRIPT XML (Layer A)

**Goal**: Verify `driver.lint()` validates FloSCRIPT XML structure.

**Test matrix**:
| Input | Expected `ok` | Diagnostics |
|-------|---------------|-------------|
| XML-1 (Grid-HeatSinks) | `True` | Warning: no solve command |
| XML-2 (Make_Tube) | `True` | Warning: no solve command |
| Malformed XML | `False` | Error: XML parse error |
| Empty file | `False` | Error: Script is empty |

---

## EX-04 — File Type Detection (Layer A)

**Goal**: Verify `driver.detect()` correctly identifies Flotherm files.

**Test matrix**:
| Input | Expected |
|-------|----------|
| `.pack` file | `True` |
| FloSCRIPT `.xml` (has `<xml_log_file>`) | `True` |
| FloXML `.xml` (has `<xmlProject>`) | `False` |
| `.py` file | `False` |
| `.txt` file | `False` |

---

## EX-05 — Batch Solve Attempt (Layer A — Known Failure)

**Goal**: Document the batch mode failure for regression tracking.

**What happens**: `driver.run_file(pack, mode="batch")` invokes `floserv.exe 16 -b <project>`. In Flotherm 2504, floserv fails to initialize the RunTable and falls through to the translator path.

**Observed behavior**:
| Field | Value |
|-------|-------|
| `exit_code` | `0` (misleading — floserv exited normally without solving) |
| `stdout` | empty |
| `stderr` | `registerStart runTable exception: invalid map<K, T> key` |
| `floerror.log` | `E/11029 - Failed unknown file type` + `E/9012 - Too few grid-cells` |
| Field files modified | `0` (solve never ran) |
| `duration_s` | ~2s (too fast for a real CFD solve) |

**True acceptance criteria** (what a REAL solve should produce):
| Criterion | Description |
|-----------|-------------|
| Field files modified | `DataSets/BaseSolution/msp_*/end/Temperature` timestamp changes |
| No E/11029 in floerror.log | Translator path not taken |
| No E/9012 in floerror.log | Real grid used, not 1x1 fallback |
| `duration_s > 5` | Real CFD solve takes at least several seconds |

**Root cause**: See `skills/flotherm-sim/known_issues.md`

---

## EX-06 — Output Parsing (Layer A)

**Goal**: Verify `parse_output()` extracts JSON from stdout.

**Test matrix**:
| Input stdout | Expected result |
|---|---|
| `""` (empty) | `{}` |
| `"no json here"` | `{}` |
| `'{"temp": 85.3}'` | `{"temp": 85.3}` |
| Multi-line with JSON as last line | Last JSON line extracted |
| Multiple JSON lines | Last one wins |
| Invalid JSON line followed by valid | Valid one returned |

---

## EX-07 — Error Paths (Layer A)

**Goal**: Verify error handling for edge cases.

| Scenario | Expected |
|---|---|
| Flotherm not installed (mocked) | `RuntimeError` with "Flotherm" in message |
| `.xml` passed to `run_file` | `NotImplementedError` with Phase 2 guidance |
| Unknown file type `.txt` | `RuntimeError` with "Unsupported file type" |

---

## Recommended Run Order

| Order | Case | Requires Flotherm | Why |
|---|---|---|---|
| 1 | EX-01 | Yes | Connectivity gate |
| 2 | EX-02 | No | Lint validation |
| 3 | EX-03 | No | FloSCRIPT lint |
| 4 | EX-04 | No | Detection logic |
| 5 | EX-06 | No | Output parsing |
| 6 | EX-07 | No | Error paths |
| 7 | EX-05 | Yes | Batch mode regression (known failure) |

---

## Test Result Summary (2026-04-01)

| Case | Status | Notes |
|------|--------|-------|
| EX-01 | **PASS** | `status=ok, version=2504` |
| EX-02 | **PASS** | Both .pack files lint OK |
| EX-03 | **PASS** | XML lint OK, correct "no solve" warning |
| EX-04 | **PASS** | .pack=True, FloSCRIPT .xml=True |
| EX-05 | **KNOWN FAIL** | Batch mode broken, see known_issues.md |
| EX-06 | **PASS** | All parsing cases correct |
| EX-07 | **PASS** | Error paths raise correct exceptions |
