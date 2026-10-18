# Flotherm Runtime Validation Report

**Date**: 2026-04-02  
**Reviewer**: Claude (automated review)  
**Scope**: `sim/src/sim/drivers/flotherm/` (driver + runtime) after refactoring  
**Test environment**: Windows 11, Simcenter Flotherm 2504, Python 3.13.5

---

## 1. Executive Summary

**Maturity stage**: The driver/runtime is architecturally complete for the job-oriented lifecycle model. It is NOT yet capable of executing a real CFD solve, because no automated execution backend exists. The maturity is "infrastructure proven, execution unproven."

**Real example execution**: No. No example has been solved end-to-end through the runtime. The full lifecycle (launch -> load_project -> submit_job -> query) has been executed against Mobile_Demo-Steady_State.pack, but the job terminates at `WAITING_BACKEND` because NullBackend cannot dispatch to Flotherm.

**Runtime structure**: Proven correct for the NullBackend path. Session state transitions, job state machine, multi-signal status detection, artifact collection, and floerror.log baseline filtering are all tested with fake data. The `SUCCEEDED`/`FAILED`/`RUNNING` paths in `detect_job_state()` are unit-tested with synthetic file/log data, but never triggered through a real Flotherm solve.

**Primary unresolved problem**: No execution backend. Flotherm 2504's batch mode (`-b`) is broken (vendor defect). No external API exists to send FloSCRIPT to a running floserv. The runtime correctly models this gap as `WAITING_BACKEND` rather than hiding it.

---

## 2. Current Code Structure

```text
sim/src/sim/drivers/flotherm/
├── __init__.py           # Package export: FlothermDriver           [existing, unchanged]
├── driver.py             # Thin DriverProtocol wrapper              [rewritten: was 415 lines, now 170]
├── runtime.py            # FlothermRuntime: session/job lifecycle    [NEW: 320 lines]
├── models.py             # Dataclasses + enums                      [NEW: 223 lines]
├── install.py            # find_installation, extract_version        [EXTRACTED from old driver.py]
├── lint.py               # lint_pack, lint_floscript                [EXTRACTED from old driver.py]
├── script_builder.py     # FloSCRIPT XML generation                 [NEW: 95 lines]
└── status.py             # Multi-signal job state detection          [NEW: 225 lines]
```

| Module | Origin | Lines | What it does |
|--------|--------|-------|-------------|
| `driver.py` | Rewritten | 170 | DriverProtocol surface. Delegates all logic to other modules. |
| `runtime.py` | New | 320 | Session lifecycle, job submission, backend dispatch, watch loop. |
| `models.py` | New | 223 | `SessionState`, `JobState` enums; `SessionInfo`, `ProjectInfo`, `JobRecord`, `ArtifactSet` dataclasses. |
| `install.py` | Extracted | 110 | `find_installation()` with env/PATH/glob search. `extract_version()`, `pack_project_dir()`. |
| `lint.py` | Extracted | 115 | `lint_pack()` (ZIP validation), `lint_floscript()` (XML + root + solve command check). |
| `script_builder.py` | New | 95 | `build_solve_and_save()`, `build_custom()`, etc. Generates FloSCRIPT XML via ElementTree. |
| `status.py` | New | 225 | `detect_job_state()` with 5 signals, `snapshot_result_files()`, `read_floerror_log()`, `collect_artifacts()`. |

---

## 3. Runtime Lifecycle and State Model

### 3.1 Session lifecycle

| Transition | Trigger | Tested | Evidence |
|-----------|---------|--------|----------|
| `None` -> `READY` | `launch()` | Yes (`test_launch_sets_ready`) | Fake install, patched `_launch_gui` |
| `None` -> `LAUNCH_FAILED` | `launch()` with no install | Yes (`test_launch_not_installed_raises_and_sets_failed`) | Patched `find_installation=None` |
| `READY` -> `DISCONNECTED` | `disconnect()` | Yes (`test_disconnect_sets_disconnected`) | Unit test |
| `DISCONNECTED` -> `READY` | `launch()` again | Yes (`test_launch_after_disconnect_succeeds`) | Unit test |
| `READY` -> `READY` (blocked) | `launch()` while active | Yes (`test_launch_when_already_active_raises`) | Raises RuntimeError |
| `None` -> submit | `submit_job()` before launch | Yes (`test_submit_before_launch_raises`) | Raises RuntimeError |

Real Flotherm evidence for session lifecycle: `launch()` was called against real installation (session_id `ea0a3cc2-...`), `load_project()` extracted Mobile_Demo .pack to `FLOUSERDIR`, `disconnect()` set state to `disconnected`. **But no floserv process was started** (headless mode with patched `_launch_gui`).

### 3.2 Job lifecycle

| Transition | Unit tested | Real Flotherm evidence | Notes |
|-----------|-------------|----------------------|-------|
| `PENDING` -> `WAITING_BACKEND` (NullBackend) | Yes (`test_null_backend_produces_waiting_backend`) | Yes (job `edbd6c92-...`) | Default path when no backend |
| `PENDING` -> `DISPATCHED` (FakeBackend returns True) | Yes (`test_fake_backend_dispatch_ok_produces_dispatched`) | No | Synthetic backend only |
| `PENDING` -> `WAITING_BACKEND` (FakeBackend returns False) | Yes (`test_fake_backend_dispatch_fail_produces_waiting`) | No | Synthetic backend only |
| `DISPATCHED` -> `SUCCEEDED` (field files changed) | Yes (`test_fields_changed_no_errors_succeeds`) | **No** | status.py tested with fake files, never triggered by real solve |
| `DISPATCHED` -> `FAILED` (fatal error in log) | Yes (`test_fatal_error_no_changes_fails`) | **No** | status.py tested with fake log, never triggered by real solve |
| `DISPATCHED` -> `TIMEOUT` | Yes (`test_timeout_no_changes_times_out`) | **No** | Simulated elapsed_s >= timeout_s |
| `DISPATCHED` -> `RUNNING` (process alive, not timed out) | Code exists | **No** | Not unit-tested (requires `is_process_alive` to return True) |
| `DISPATCHED` -> `UNKNOWN` | Yes (`test_no_changes_no_errors_process_dead_unknown`) | **No** | No evidence either way |
| `WAITING_BACKEND` -> (no transition) | Yes (`test_watch_job_waiting_backend_returns_immediately`) | Yes | `watch_job` returns immediately |

**Summary**: The `PENDING -> WAITING_BACKEND` transition is the only one exercised against real Flotherm assets. All SUCCEEDED/FAILED/TIMEOUT/RUNNING transitions are unit-tested with synthetic data but have zero real Flotherm evidence.

---

## 4. Driver/Runtime Entry Consistency

### 4.1 `.pack` entry

Call chain:
```
driver.run_file(Path("model.pack"))
  -> driver._run_pack_via_runtime(pack)
    -> FlothermRuntime()
    -> rt.launch(ui_mode="gui")
    -> rt.load_project(pack)       # extracts .pack to FLOUSERDIR
    -> rt.submit_job(label="solve-all")  # auto-generates FloSCRIPT, dispatches to backend
    -> rt.watch_job(job_id)         # if WAITING_BACKEND, returns immediately
    -> driver._job_to_run_result(job, pack)  # converts JobRecord -> RunResult
```

No old logic remains. Verified by `test_run_file_pack_returns_structured_result`:
```python
result = d.run_file(pack)
assert "state:" in result.stdout
assert "job_id:" in result.stdout
assert result.solver == "flotherm"
```

### 4.2 `.xml` entry

Call chain:
```
driver.run_file(Path("script.xml"))
  -> driver._run_xml_via_runtime(script)
    -> FlothermRuntime()
    -> rt.launch(ui_mode="gui")
    -> rt.exec_floscript(script)    # reads XML file, creates job
    -> rt.watch_job(job_id)
    -> driver._job_to_run_result(job, script)
```

**No `NotImplementedError`**. Verified by `test_run_file_xml_no_not_implemented_error`:
```python
d = FlothermDriver()
result = d.run_file(xml)
assert "waiting_backend" in result.stdout
assert result.exit_code == 3
```

And `test_run_xml_returns_waiting_backend` in test_batch_execution.py:
```python
result = FlothermDriver().run_file(xml)
assert result.exit_code == 3
assert "waiting_backend" in result.stdout
```

### 4.3 `create_runtime()` vs `run_file()`

`driver.run_file()` creates an ephemeral runtime per call (launch -> work -> disconnect).
`driver.create_runtime()` returns a bare `FlothermRuntime` for the agent to manage manually.

They share the same `FlothermRuntime` class. The difference: `run_file` is a one-shot convenience wrapper; `create_runtime` gives the agent persistent session control. No semantic divergence — both use the same `submit_job` / `watch_job` logic.

---

## 5. Real Example Execution Evidence

### 5.1 Example identity

| Field | Value |
|-------|-------|
| Input file | `E:\Program Files (x86)\Siemens\SimcenterFlotherm\2504\examples\FloSCRIPT\Demonstration Examples\Transient Power Update\Mobile_Demo-Steady_State.pack` |
| Type | `.pack` |
| Project name | `Mobile_Demo_Steady_State` |
| Project dir | `Mobile_Demo_Steady_State.002ED56414BAD1BD526E658D00000051` |
| Backend | `NullBackend` ("none") |
| Execution command | Python: `FlothermRuntime.launch() -> load_project() -> submit_job()` |

### 5.2 Runtime evidence

| Step | Output |
|------|--------|
| session_id | `ea0a3cc2-4624-4e3a-8a89-1638a6a3efcf` |
| session.state after launch | `ready` |
| project.source | `pack` |
| project.scenario_dirs | `["msp_0", "msp_1"]` |
| project.has_ccstatefile | `false` |
| job_id | `edbd6c92-1b26-4650-8ac4-e0a3d3350fa6` |
| job.state | `waiting_backend` |
| job.started_at | `null` (never started) |
| job.ok | `false` |
| dispatch_metadata.backend | `"none"` |
| dispatch_metadata.reason | `"No automated execution backend available"` |
| dispatch_metadata.pre_solve_snapshot | 26 field files with mtimes captured |
| dispatch_metadata.floerror_baseline | `""` (empty — no prior errors) |
| query_status.run_count | `1` |
| query_status.process_alive | `false` |
| query_artifacts.modified_fields | `[]` (empty — no solve ran) |
| query_artifacts.result_dirs | `["msp_0", "msp_1"]` |
| query_artifacts.generated_scripts | `["...\\_sim_solve-all.xml"]` |
| session.state after disconnect | `disconnected` |

### 5.3 File-system evidence

| Path | Before | After | Interpretation |
|------|--------|-------|----------------|
| `FLOUSERDIR/Mobile_Demo_Steady_State.002ED564.../` | Existed from prior unpack | Unchanged | Project directory present but untouched |
| `FLOUSERDIR/_sim_solve-all.xml` | Did not exist | 317 bytes, valid FloSCRIPT XML | Runtime generated the solve script |
| `FLOUSERDIR/_sim_launch.bat` | Did not exist | 98 bytes | Flotherm GUI launcher wrapper (not invoked in headless mode) |
| `FLOUSERDIR/floerror.log` | Did not exist | Did not exist | No floserv ran, so no error log generated |
| `DataSets/BaseSolution/msp_0/end/Temperature` | 11632 bytes, mtime=09:21 | 11632 bytes, mtime=09:21 | **Unchanged** — no solve executed |
| `DataSets/BaseSolution/msp_1/end/Temperature` | 11632 bytes, mtime=09:21 | 11632 bytes, mtime=09:21 | **Unchanged** |

### 5.4 Conclusion for this example

**This example completed the runtime lifecycle but did NOT execute a solve.**

Classification: "Only completed runtime lifecycle, no solve dispatched."

Evidence:
- Job state = `WAITING_BACKEND` (no backend dispatched the FloSCRIPT)
- `job.started_at = null` (execution never began)
- Zero field files modified
- No `floerror.log` created (no floserv process ran)
- The generated `_sim_solve-all.xml` is syntactically valid (passes `lint_floscript`) but was never fed to Flotherm

**There is no example in the current test history that proves a real Flotherm solve completed through the runtime.**

---

## 6. Test Coverage Summary

| Category | Test file | Count | What it proves | What it does NOT prove |
|----------|-----------|-------|---------------|----------------------|
| Detect/lint (.pack + .xml) | test_batch_execution.py | 6 | Correct identification and validation of .pack/.xml files against real Flotherm 2504 examples | N/A — these are fully proven |
| Install/version detection | test_runtime.py | 7 | `extract_version`, `default_flouser`, `pack_project_dir` work for standard and edge-case paths | Not tested against non-2504 versions |
| Script builder round-trip | test_runtime.py | 3 | Generated FloSCRIPT XML passes `lint_floscript` | Does not prove Flotherm can actually execute the generated XML |
| Session lifecycle | test_runtime.py | 8 | State transitions: launch, disconnect, double-launch, not-installed, reconnect | All use fake install + patched `_launch_gui`. No real floserv started. |
| Job state machine | test_runtime.py | 7 | NullBackend -> WAITING_BACKEND, FakeBackend -> DISPATCHED, dispatch-fail, run_count, watch | SUCCEEDED/FAILED/RUNNING paths only tested in status.py, not through runtime.watch_job |
| Status conflict-signal detection | test_runtime.py | 6 | Fields-changed, fatal-error, timeout, conflict (fields+fatal), empty-snapshot safety, reasons populated | Synthetic files/logs only. Never validated against real floserv output. |
| Bug regressions | test_runtime.py | 3 | BUG-1: snapshot preserved. BUG-2: stale log filtered. BUG-2b: empty snapshot safe. | Bugs were found by tests and fixed. |
| Artifact collection | test_runtime.py | 3 | Artifacts collectible in WAITING_BACKEND, nonexistent dir safe, no-jobs error | Not tested with real solve output |
| Driver/runtime consistency | test_runtime.py | 2 | `.xml` no longer raises NotImplementedError. `.pack` returns structured result. | Both go through NullBackend. |
| Backend contract | test_runtime.py | 2 | FakeBackend dispatch_ok=True -> DISPATCHED. dispatch_ok=False -> WAITING_BACKEND. | Only FakeBackend tested. No real backend exists. |
| Output parsing | test_batch_execution.py | 5 | parse_output extracts JSON correctly | Floserv stdout is empty in real execution. Parsing logic never exercised against real output. |
| Skill structure docs | test_skill_structure.py | 28 | Reference documents exist and contain required content | These are documentation tests, not behavior tests |

**Totals**: 86 tests passed, 7 deselected (@slow, require real Flotherm execution), 0 failed.

**Critical gap**: All 86 passing tests use fake backends, fake files, or fake installation. **Zero tests exercise a real Flotherm floserv process through the runtime.** The @slow tests in test_batch_execution.py now check for `WAITING_BACKEND` rather than `exit_code=0`, reflecting the actual runtime behavior.

---

## 7. Bugs Fixed vs Backend Gaps vs Vendor Defects

| Issue | Classification | Evidence |
|-------|---------------|----------|
| NullBackend.dispatch() replaced `dispatch_metadata` dict, destroying `pre_solve_snapshot` | **Code defect (fixed)** | Test `test_null_backend_preserves_snapshot` — failed before fix, passes after. Fix: changed `=` to `.update()`. |
| `detect_job_state()` read ALL historical errors from `floerror.log`, false FAILED for new jobs | **Code defect (fixed)** | Test `test_stale_error_log_does_not_cause_false_failure`. Fix: added `floerror_baseline` parameter; runtime captures baseline at submit time. |
| `diff_result_files()` treated all files as "new" when `pre_solve_snapshot` was empty → false SUCCEEDED | **Code defect (fixed)** | Test `test_empty_snapshot_no_false_positive`. Fix: when snapshot is empty, field change detection is disabled. |
| Cannot send FloSCRIPT to running floserv from external process | **Backend gap** | Flotherm uses proprietary named-pipe protocol between floserv and children. No TCP/gRPC/COM interface documented. Tested: pipe names not discoverable, no TCP ports open. |
| `flotherm.bat -b` broken in Flotherm 2504 | **Vendor defect** | `registerStart runTable exception: invalid map<K, T> key`. Tested with: all project name formats, all license configs, all FLOUSERDIR configs, registered/unregistered projects. All produce identical E/11029 + E/9012. |
| Job state `WAITING_BACKEND` when no backend can execute | **Backend gap (correctly modeled)** | `dispatch_metadata` contains structured instructions. `job.ok = false`. `exit_code = 3`. Not a code defect — this is the correct representation of the gap. |
| `SUCCEEDED`/`FAILED`/`RUNNING` transitions never triggered by real data | **Backend gap** | These paths exist in `detect_job_state()` and are unit-tested with synthetic data, but no real backend has produced the signals needed to trigger them. |

---

## 8. First-Principles Evaluation

### 8.1 Control face vs observation face: are they separated?

**Judgment: Yes.**

Control (mutation): `launch()`, `load_project()`, `submit_job()`, `exec_floscript()`, `disconnect()`.
Observation (query): `query_status()`, `query_artifacts()`, `watch_job()`, `get_job()`.

Evidence: `query_status()` and `query_artifacts()` are read-only — they don't modify session or job state. `watch_job()` does update `job.state` but only based on observation signals, not control actions.

Gap: `watch_job()` both observes AND updates state. A strict separation would have a separate `update_job_state()` call. This is acceptable for the polling model but would need revisiting if real-time events are added.

### 8.2 Real capabilities vs capability gaps: are they separated?

**Judgment: Yes. This is the strongest aspect of the refactoring.**

Evidence: `ExecutionBackend` protocol with `can_execute()` and `dispatch()`. `NullBackend` explicitly returns `False` from `dispatch()`, and the job enters `WAITING_BACKEND` with structured `dispatch_metadata`. The agent sees `state=waiting_backend` and `reason="No automated execution backend available"`, not a print message or exception.

Remaining concern: `_launch_gui()` in `runtime.py` still launches a Flotherm GUI process even though NullBackend can't use it. Test `test_run_file_pack_no_gui_spawn` currently passes because `ui_mode="headless"` skips the GUI. But the default `ui_mode="gui"` in `driver._run_pack_via_runtime()` would launch a useless process.

### 8.3 Is the job state machine the central abstraction?

**Judgment: Yes, but with a caveat.**

Evidence: All execution paths go through `submit_job()` -> `JobRecord` with `JobState`. `watch_job()` polls `detect_job_state()` which returns `(JobState, reasons)`. The agent always gets a `JobRecord.to_dict()` with `state`, `state_reasons`, `artifacts`.

Caveat: `driver.run_file()` converts the `JobRecord` to a `RunResult` via `_job_to_run_result()`, which maps `JobState` to `exit_code` integers. This is a lossy conversion required by `DriverProtocol`. Agents using `create_runtime()` directly get the full `JobRecord` and don't lose information.

### 8.4 Is state determination multi-signal, not single-point heuristic?

**Judgment: Yes in code. Unproven with real data.**

Evidence: `detect_job_state()` combines 5 signals:
1. Field file mtime changes (pre/post snapshot comparison)
2. `floerror.log` new errors (baseline-filtered)
3. Process PID alive check
4. Elapsed time vs timeout
5. Empty-snapshot guard (prevents false positives)

Tested with synthetic data:
- `test_fields_changed_no_errors_succeeds` — signal 1 alone
- `test_fatal_error_no_changes_fails` — signal 2 alone
- `test_timeout_no_changes_times_out` — signal 4 alone
- `test_fields_changed_but_fatal_error_should_fail` — signal 1 + 2 conflict
- `test_stale_error_log_does_not_cause_false_failure` — signal 2 with baseline
- `test_empty_snapshot_no_false_positive` — signal 1 edge case

Not tested: signal 3 (process alive with real PID), signal combinations from real Flotherm output.

### 8.5 Is the backend truly replaceable?

**Judgment: Mostly yes. One concern.**

What a new `GuiAutomationBackend` would need to implement:
```python
class GuiAutomationBackend:
    @property
    def name(self) -> str:
        return "gui_automation"
    
    def can_execute(self) -> bool:
        return True  # pywinauto available
    
    def dispatch(self, job: JobRecord, session: SessionInfo) -> bool:
        # 1. Find Flotherm GUI window
        # 2. Click Project > Run Script > job.script_path
        # 3. Return True (dispatched)
        ...
```

Changes required in runtime.py: **Zero.** The runtime calls `self._backend.dispatch(job, session)` and checks the return value. If `True`, job moves to `DISPATCHED` and `watch_job` starts polling `detect_job_state()`.

Concern: The `ExecutionBackend.dispatch()` contract is synchronous and returns `bool`. A real backend might need async dispatch (e.g., GUI automation takes time). The current contract assumes dispatch is fast and the actual execution is detected via `watch_job`. This works for GUI automation (click and return), but might not work for a batch backend that blocks.

### 8.6 Is the architecture general?

| Dimension | Proven | Evidence |
|-----------|--------|----------|
| Different .pack structures | Partially | Mobile_Demo (no ccstatefile) and SuperPosition (with ccstatefile) both load. Multi-toplevel ZIP tested. |
| Different FloSCRIPT commands | Yes | `build_solve_and_save`, `build_solve_all`, `build_custom`, `build_solve_scenario` all generate valid XML (lint round-trip tested). |
| Different workspace states | Partially | Tested with existing project (skip re-extract) and fresh extract. Not tested with conflicting project dirs. |
| Different backends | Yes (structurally) | NullBackend, BatchBackend, FakeBackend all work. But no real backend exists. |
| Different Flotherm versions | No evidence | Only tested with 2504. `extract_version` handles path patterns but no other version tested. |

### 8.7 Is the architecture extensible?

| Extension | Effort estimate | Return work risk |
|-----------|----------------|------------------|
| Add GUI automation backend | Implement `ExecutionBackend` (3 methods). No runtime changes. | **Low** — clean interface. |
| Add richer artifact parsing | Extend `collect_artifacts()` in status.py. Add fields to `ArtifactSet`. | **Low** — additive. |
| Add new job types (e.g., "mesh-only", "export-only") | New `script_builder` functions + new labels. Same `submit_job` path. | **Low** — existing job model handles it. |
| Add more project operations (parameterize, DOE) | New FloSCRIPT builder functions. `exec_floscript()` already accepts any XML. | **Low**. |
| Support persistent session across multiple submit_job calls | Already works — `create_runtime()` returns a long-lived runtime. | **None** — already designed for this. |
| Support real-time solve progress (residuals, iteration count) | Requires new signal in `detect_job_state()` or new query method. | **Medium** — `detect_job_state` would need a "progress" signal source. |

---

## 9. Open Questions / Missing Evidence

| Question | Why it matters | What evidence is missing | Suggested next step |
|----------|---------------|------------------------|-------------------|
| Has any real example completed a solve through the runtime? | Without this, the SUCCEEDED/FAILED paths are theoretical. | Zero field files have ever been modified by a runtime-dispatched job. | Implement a `GuiAutomationBackend` or fix batch mode. |
| Does `detect_job_state()` work correctly against real floserv output? | Synthetic tests may miss real-world signal patterns. | No real `floerror.log` from a runtime-initiated solve has been processed. | Run a manual solve, capture floerror.log, feed to `detect_job_state`. |
| Is the `floerror_baseline` approach robust? | Log format may vary across Flotherm versions or locales. | Only tested with English error messages. | Test with actual Flotherm log files from different scenarios. |
| Does `_launch_gui()` produce a usable floserv process? | The GUI launch code exists but was always mocked in tests. | No test verifies that a launched floserv responds to commands. | Start floserv, verify PID alive, verify GUI window exists. |
| Will the first real backend expose contract gaps? | `dispatch()` returns `bool` synchronously — may be insufficient. | No real backend has been implemented. | Implement the simplest possible backend (e.g., batch with process capture) and observe. |
| Is `_job_to_run_result()` exit_code mapping correct? | `exit_code=3` for WAITING_BACKEND is arbitrary. | No external consumer has validated the mapping. | Define exit_code contract in documentation. |

---

## 10. Appendices

### A. Key test names

**Bug regression tests** (test_runtime.py):
- `TestBug1_SnapshotPreserved::test_null_backend_preserves_snapshot`
- `TestBug2_FloerrorLogHistorical::test_stale_error_log_does_not_cause_false_failure`
- `TestBug4_NoGuiLaunchWithNullBackend::test_run_file_pack_no_gui_spawn`

**`.xml` unified entry test** (test_runtime.py + test_batch_execution.py):
- `TestDriverRuntimeConsistency::test_run_file_xml_no_not_implemented_error`
- `TestNotInstalled::test_run_xml_returns_waiting_backend`

**Session lifecycle** (test_runtime.py):
- `TestSessionLifecycle::test_initial_state_is_none`
- `TestSessionLifecycle::test_launch_sets_ready`
- `TestSessionLifecycle::test_disconnect_sets_disconnected`
- `TestSessionLifecycle::test_launch_when_already_active_raises`
- `TestSessionLifecycle::test_launch_after_disconnect_succeeds`
- `TestSessionLifecycle::test_launch_not_installed_raises_and_sets_failed`
- `TestSessionLifecycle::test_session_fields_populated`
- `TestSessionLifecycle::test_submit_before_launch_raises`

**Job state machine** (test_runtime.py):
- `TestJobStateMachine::test_null_backend_produces_waiting_backend`
- `TestJobStateMachine::test_fake_backend_dispatch_ok_produces_dispatched`
- `TestJobStateMachine::test_fake_backend_dispatch_fail_produces_waiting`

**Conflict-signal detection** (test_runtime.py):
- `TestDetectJobState::test_fields_changed_no_errors_succeeds`
- `TestDetectJobState::test_fatal_error_no_changes_fails`
- `TestDetectJobState::test_timeout_no_changes_times_out`
- `TestDetectJobState::test_fields_changed_but_fatal_error_should_fail`
- `TestDetectJobState::test_empty_snapshot_no_false_positive`

**Script builder round-trip** (test_runtime.py):
- `TestScriptBuilderLintRoundTrip::test_solve_and_save_passes_lint`
- `TestScriptBuilderLintRoundTrip::test_solve_all_passes_lint`
- `TestScriptBuilderLintRoundTrip::test_custom_commands_passes_lint`

### B. Key log excerpts

**Real runtime lifecycle output** (captured 2026-04-02T03:01):
```json
SESSION: {"session_id": "ea0a3cc2-4624-4e3a-8a89-1638a6a3efcf", "state": "ready", "workspace": "...\\flouser", "version": "2504"}
PROJECT: {"project_name": "Mobile_Demo_Steady_State", "scenario_dirs": ["msp_0", "msp_1"], "source": "pack"}
JOB:     {"job_id": "edbd6c92-...", "state": "waiting_backend", "ok": false, "backend": "none"}
STATUS:  {"run_count": 1, "process_alive": false, "total_jobs": 1}
ARTIFACTS: {"modified_fields": [], "result_dirs": ["msp_0", "msp_1"], "generated_scripts": ["...\\_sim_solve-all.xml"]}
```

**Generated FloSCRIPT** (`_sim_solve-all.xml`):
```xml
<?xml version="1.0" ?>
<xml_log_file version="1.0">
    <project_load project_name="Mobile_Demo_Steady_State"/>
    <external_command process="CommandCentre">
        <solve_all/>
    </external_command>
    <external_command process="CommandCentre">
        <save/>
    </external_command>
</xml_log_file>
```

**driver.run_file(.pack) RunResult**:
```
exit_code: 3
stdout: state: waiting_backend\njob_id: 4f3cd274-31f0-4ef0-90c6-cad54dd3fd86
stderr: No automated execution backend available
duration_s: 0.0
solver: flotherm
```

**driver.run_file(.xml) RunResult**:
```
exit_code: 3
stdout: state: waiting_backend\njob_id: b6e17708-a439-400f-8fb8-1f7063eb5d4a
stderr: No automated execution backend available
```

### C. Key code excerpts

**ExecutionBackend interface** (`runtime.py`):
```python
class ExecutionBackend(Protocol):
    @property
    def name(self) -> str: ...
    def can_execute(self) -> bool: ...
    def dispatch(self, job: JobRecord, session: SessionInfo) -> bool: ...
```

**runtime.submit_job — baseline capture** (`runtime.py:440-460`):
```python
job.dispatch_metadata["pre_solve_snapshot"] = snapshot_result_files(field_dir)
baseline_content, _, _ = read_floerror_log(session.workspace)
job.dispatch_metadata["floerror_baseline"] = baseline_content
dispatched = self._backend.dispatch(job, session)
if dispatched:
    job.state = JobState.DISPATCHED
else:
    job.state = JobState.WAITING_BACKEND
```

**status.detect_job_state — decision logic** (`status.py:165-190`):
```python
# Case 1: New fatal errors -> FAILED (regardless of field changes)
if has_fatal:
    return JobState.FAILED, reasons
# Case 2: Fields changed + no new fatal errors -> SUCCEEDED
if fields_changed:
    return JobState.SUCCEEDED, reasons
# Case 3: Process still running, no timeout -> RUNNING
if proc_alive and not timed_out:
    return JobState.RUNNING, reasons
# Case 4: Timeout reached -> TIMEOUT
if timed_out:
    return JobState.TIMEOUT, reasons
# Case 5: No evidence either way -> UNKNOWN
return JobState.UNKNOWN, reasons
```

**driver.run_file — unified entry** (`driver.py:85-100`):
```python
def run_file(self, script: Path, **kwargs) -> RunResult:
    info = find_installation()
    if info is None:
        raise RuntimeError("Simcenter Flotherm not found.")
    ext = script.suffix.lower()
    if ext == ".pack":
        return self._run_pack_via_runtime(script, **kwargs)
    if ext == ".xml":
        return self._run_xml_via_runtime(script, **kwargs)
    raise RuntimeError(f"Unsupported file type '{script.suffix}'.")
```
