---
name: flotherm-sim
description: Use when running Simcenter Flotherm thermal cases through the sim runtime. Primary path is GUI automation via pywinauto UIA (`.pack` import + FloSCRIPT playback). Direct batch (`translator.exe` + `solexe.exe`) is a headless optimization for re-solving existing projects only.
---

# flotherm-sim

You are connected to **Simcenter Flotherm** via sim-cli. This file is
the **index**. It tells you where to look for actual content — it does
not contain the content itself.

The `/connect` response told you which active layer applies via:

```json
"skills": {
  "root":               "<sim-plugin-flotherm>/_skills/flotherm",
  "active_sdk_layer":   null,        // Flotherm has no Python SDK
  "active_solver_layer":"2504"       // or "2412" / "2406"
}
```

Always read `base/`, then your active `solver/<version>/`. There is no
`sdk/` overlay because Flotherm has no Python wrapper — the driver
controls Flotherm via pywinauto UIA (Qt menu automation) + Win32
ctypes (standard file dialogs).

---

## Execution paths

### GUI automation — primary path (recommended)

All vendor-documented CLI playback modes are broken in Flotherm 2504 (see `known_issues.md` ISSUE-001). GUI automation via pywinauto UIA is the only verified end-to-end working path for `.pack` import, FloSCRIPT playback, and first-time project creation/modification.

```bash
uv run sim connect --solver flotherm --ui-mode gui     # launch Flotherm GUI (needs RDP/interactive desktop)
uv run sim exec '<path>.pack'                          # import pack into GUI
uv run sim exec 'solve'                                # run CFD solve
uv run sim exec 'status'                               # query session state
uv run sim disconnect                                  # kill all processes
```

**Requirements**: `uv run sim serve` must run in an interactive desktop session (RDP, not SSH session 0). The GUI binary needs a real desktop to render Qt widgets.

### Direct batch — headless optimization for re-solves only

Bypasses floserv — calls translator and solver executables directly. Works from SSH with no interactive desktop, BUT only for projects that already exist in `FLOUSERDIR` (i.e., previously imported/created via the GUI path).

```batch
call flotherm.bat -env                              :: set environment only
translator.exe -p "<FLOUSERDIR>\<project>.<GUID>" -n1   :: discretize model → msp_0
solexe.exe -p "<FLOUSERDIR>\<project>.<GUID>"           :: run CFD solver
```

**What this path can do**:
- Re-solve an existing project with no parameter changes (e.g., crash recovery, rerun with different iteration count after manually editing `solver_control`)
- Run on a Flotherm project that was originally imported via the GUI path
- Fully headless, fully scriptable, works from SSH

**What this path cannot do**:
- Create a new project from scratch
- Import a `.pack` file (needs GUI automation)
- Modify model parameters (requires FloSCRIPT playback, which is broken in CLI)
- Change geometry, materials, boundary conditions, power values, etc.

**Solver log**: `<project>/DataSets/BaseSolution/PDTemp/logit`  
**Result fields**: `<project>/DataSets/BaseSolution/msp_*/end/Temperature` etc.  
**Solver variants**: `solexe.exe` (single), `solexed.exe` (double), `solexe_p.exe` (parallel)

### Decision rule

- **Need to import a `.pack` or create/modify a project?** → GUI automation
- **Just re-solving an existing unmodified project?** → Direct batch (faster, headless)
- **Need model parameter modification headlessly?** → Not yet possible (see `known_issues.md` ISSUE-003)

### How GUI automation works

```
uv run sim exec → driver.run() → _play_floscript(script_path)
  ├─ subprocess: pywinauto UIA expand() Macro → invoke() Play FloSCRIPT
  │  (invoke blocks due to modal dialog; subprocess killed after timeout)
  └─ main process: Win32 ctypes fills file dialog → clicks Open
```

UIA runs in a **subprocess** to isolate COM state corruption from the
server process. The file dialog is a standard Windows dialog, handled
via `GetDlgItem(1148)` + `SendMessage(WM_SETTEXT)` + `BM_CLICK`.

---

## base/ — always relevant

| Path | What's there |
|---|---|
| `base/reference/floscript_modeling.md` | **FloSCRIPT model generation reference** — command vocabulary, patterns, step templates for building models from scratch via Claude. Includes the `project_run_script` chaining pattern and a pointer to the full 620-command catalogue. |
| `base/reference/postprocessing.md` | **Result extraction reference** — FloSCRIPT export commands (Path A), direct binary read of `msp_*/end/<Field>` files (Path B, format verified), GUI export (Path C), plus copy-paste verification probes. |
| `base/reference/error_codes.md` | **Triage table** for `E/<NNNNN>` / `W/<NNNNN>` / `I/<NNNNN>` codes seen in `floerror.log` and `WinXP\bin\LogFiles\logFile*.xml`. Read this when an `ok=false` result needs a retry-vs-fatal decision. |
| `base/reference/headless_bootstrap_investigation.md` | **What's ruled out, what's open** for headless project authoring (overlay approach is dead; GUI bootstrap is the next experiment) and `<load_from_library>` `E/15001` (9 syntactic forms ruled out; recording oracle deferred). |
| `base/reference/` | FloSCRIPT XML patterns, GUI control sequences, Win32 message recipes. |
| `base/workflows/` | End-to-end demo runs of typical Phase A `.pack` cases. |
| `base/docs/` | Background on the GUI-automation approach and why headless batch is broken upstream. |
| `base/skill_tests/` | Skill QA cases (kept inside `base/` for flotherm because the GUI playback IS the skill — there's no separate Python control surface). |

## solver/<active_solver_layer>/ — release specifics

Empty stubs by default; per-release deltas land here as discovered.

- `solver/2504/notes.md` — 2025.1, current
- `solver/2412/notes.md` — 2024.4
- `solver/2406/notes.md` — 2024.2

## known_issues.md and tests/ (top-level)

Top-level QA artifacts. `known_issues.md` documents the
vendor-defect-broken headless batch mode. `tests/` is the pytest suite
for the inline driver. Not loaded during a normal session.

---

## Example files (reference only)

This skill's workflow scripts and `skill_tests/` reference vendor-shipped
demo models by the paths where they live inside a local Flotherm install.
This skill does **not** bundle any of that content (it is
proprietary Siemens / Mentor Graphics material and was removed under
issue #2 for IP compliance). To reproduce the tests, point the helpers at
your own Flotherm 2504 install — default on Windows is
`C:\Program Files\Siemens\SimcenterFlotherm\2504\examples\` (override in
`flotherm/tests/execution/run_helpers.ps1` if installed elsewhere).

| File referenced in this skill | Location inside `…\2504\examples\` |
|---|---|
| `Mobile_Demo-Steady_State.pack` | `FloSCRIPT\Demonstration Examples\Transient Power Update\` |
| `SuperPosition.pack` | `Demonstration Models\Superposition\` |
| `Grid-HeatSinks-and-Fans.xml`, `Make_Tube.xml`, `linear-relaxation-setup.xml`, `Remove-All-Grid.xml`, `reset_solver_controls.xml` | `FloSCRIPT\Utilities\` and `FloSCRIPT\Demonstration Examples\Voxelization\` |
| FloSCRIPT XSD schemas (`FloSCRIPTSchema.xsd`, `CommonCommands.xsd`, `CoreFloviewCommands.xsd`, …) | `FloSCRIPT\Schema\` |
| `FloSCRIPT_Rack.cls` VBA module | `DCIM\` |

For Flotherm 2410, the same subpaths apply under
`C:\Program Files\Siemens\SimcenterFlotherm\2410\examples\`.

## Model generation (building from scratch)

To build a Flotherm model from a natural language description, generate
FloSCRIPT XML step by step. See `base/reference/floscript_modeling.md`
for the full command reference, common patterns, and pitfalls.

```bash
uv run sim connect --solver flotherm --ui-mode gui
uv run sim lint step1.xml                          # XSD validates automatically
uv run sim exec step1.xml                          # create geometry + save checkpoint
uv run sim lint step2.xml
uv run sim exec step2.xml                          # add sources + save checkpoint
uv run sim exec 'solve'                            # run CFD
uv run sim disconnect
```

Each step is a separate FloSCRIPT file with `<project_save_as>` at the
end for crash recovery. Lint before play — XSD validation catches
typos and structural errors with line numbers.

## Hard constraints

1. **GUI must be visible.** The automation uses pywinauto UIA which
   requires the Flotherm window to be in an interactive desktop session.
   `uv run sim serve` must be started from RDP, not SSH.
2. **Don't open Flotherm by hand while sim is using it.** UIA element
   discovery races with user input. Let the driver own the lifecycle.
3. **UIA must run in a subprocess.** `invoke()` on Qt menu items throws
   COMError and corrupts COM state for the entire process. Always
   isolate in `subprocess.Popen` with timeout.
4. **Acceptance ≠ exit code.** Always extract a numeric (max temp,
   junction-to-ambient ΔT) from the .pack output and validate against
   the user's criterion.

---

## Required protocol

1. `uv run sim connect --solver flotherm --ui-mode gui` — launches Flotherm
2. `uv run sim exec '<path>.pack'` — imports pack (uses `project_import` FloSCRIPT with `import_type="Pack File"`)
3. `uv run sim exec 'solve'` — plays `<start start_type="solver"/>` FloSCRIPT
4. Verify solve completed: check Message Window for `I/9001 - Solver stopped: steady solution converged`
5. `uv run sim disconnect` — kills floserv, floview, flotherm

---

## GUI actuation

Flotherm's driver is the original user of the UIA subprocess +
Win32 file-dialog pattern. Starting with Phase 3 that pattern lives in
[`sim.gui._win32_dialog`](../../sim-cli/src/sim/gui/_win32_dialog.py)
and [`sim.gui._pywinauto_tools`](../../sim-cli/src/sim/gui/_pywinauto_tools.py),
shared with every other driver. Flotherm's `_win32_backend.py` now
imports from there — behaviour is unchanged, the code is no longer
duplicated.

A `gui` object is **not** injected for Flotherm sessions because the
driver's `play_floscript` helper already owns the UI interaction. If
you need generic window actions (screenshot of the Message Window
dock, a quick `list_windows()` to debug a launch), import the
primitives directly:

```python
from sim.gui import GuiController
controller = GuiController(process_name_substrings=("flotherm", "flomain"))
print(controller.list_windows())
```

See [the sim-cli `gui` skill](../sim-cli/gui/SKILL.md) for the
full API reference.
