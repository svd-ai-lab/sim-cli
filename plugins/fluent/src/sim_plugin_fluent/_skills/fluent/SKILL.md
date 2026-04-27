---
name: fluent-sim
description: Use when an agent or engineer needs to drive an Ansys Fluent meshing or solver session through the sim runtime — incremental snippet execution, single-file workflows, persistent sessions via `sim connect` / `sim exec` / `sim inspect`, or one-shot script runs.
---

# fluent-sim

You are driving **Ansys Fluent** via sim-cli in a **persistent session**.
This file is the **index** — it tells you where to look for content,
not what the content says.

> **First, read [`../sim-cli/SKILL.md`](../sim-cli/SKILL.md)** — it owns
> the shared runtime contract (session lifecycle, Step-0 version probe,
> input classification, acceptance, escalation). This skill covers only
> the Fluent-specific layer on top of that contract.

---

## Fluent-specific layered content

After `sim connect --solver fluent` and the shared-skill Step-0 probe,
the returned `session.versions` payload tells you which Fluent-specific
subfolders to load:

```json
"session.versions": {
  "profile":             "pyfluent_0_38_modern",
  "active_sdk_layer":    "pyfluent-0.38",  // or "pyfluent-0.37"
  "active_solver_layer": "25.2"            // or null
}
```

Always read `base/`, then your active `sdk/<slug>/`, then your active
`solver/<slug>/`. Later layers override earlier ones on identically
named files.

### `base/` — always relevant

| Path | What's there |
|---|---|
| `base/reference/task_templates.md` | Per-workflow input templates with "Must ask if missing" lists. **Always read first** to identify Category A inputs (per the shared skill's `input_classification.md`) before any `sim exec`. |
| `base/reference/runtime_patterns.md` | Fluent-specific dependency chains (meshing task ordering, solver step ordering). For the generic connect/exec/inspect/disconnect loop, see the shared skill's `lifecycle.md`. |
| `base/reference/acceptance_checklists.md` | Per-workflow acceptance criteria for the packaged Fluent workflows. |
| `base/reference/api_discovery.md` | `dir()` / `child_names` patterns for finding renamed attributes when an API call fails. |
| `base/reference/tui_vs_settings.md` | When to prefer the Settings API vs the legacy TUI. |
| `base/reference/pyfluent_overview.md` | Quick orientation: what PyFluent is, what each module does. |
| `base/snippets/` | Numbered EX-01 step snippets (`01_read_case.py` through `08c_extract_all_fields.py`). Built for the modern (0.38) dialect; portable to 0.37 with the material-accessor swap noted in `sdk/pyfluent-0.37/notes.md`. |
| `base/workflows/` | Multi-step demo scripts: meshing (watertight + fault-tolerant), solver exhaust manifold, flipchip thermal. |

### `sdk/<active_sdk_layer>/` — PyFluent API specifics

- `sdk/pyfluent-0.38/` — current PyFluent line.
  - `cheat_sheet.md` — most common API calls in one file.
  - `examples/` — full pyfluent.docs.pyansys.com examples (mixing_elbow,
    ahmed_body, conjugate_heat_transfer, …). Each is a working Python
    script you can quote from.
  - `user_guide/` — the upstream PyFluent user guide, mirrored.
- `sdk/pyfluent-0.37/` — legacy line.
  - `notes.md` — the one accessor difference vs 0.38 that bites EX-01.

### `solver/<active_solver_layer>/` — Fluent release specifics

- `solver/25.2/` — Fluent 25R2 (v252) quirks (currently empty stub).

### `doc-search/` — local documentation lookup

The `sdk/pyfluent-0.38/user_guide/` and `sdk/pyfluent-0.38/examples/`
folders bundled above cover **PyFluent API** usage — they are your first
stop for "how do I call X from Python?" questions.

They do **not** cover the Fluent User's Guide, Theory Guide, Tutorial
Guide, UDF Manual, or Meshing Manual. That content is **only** available
in the doc tree Ansys installs on disk, and `doc-search/` is your first
stop for Fluent-specific **solver / physics / UDF / meshing** questions.
Do not guess at model names, TUI commands, UDF macros, or physics
defaults — query the local docs:

```bash
uv run --project <sim-skills>/fluent/doc-search sim-fluent-doc search "<term>" [--module <substring>]
```

One-time setup on any host that has Ansys installed:

```bash
cd <sim-skills>/fluent/doc-search && uv sync
```

(No index build step — each query scans the doc tree in parallel; typical
latency is 1–3 s on a local SSD.)

Tips for good queries:
- Use **2–3 keywords**, not questions. It's plain substring matching.
- Filter by `--module` to bias toward a specific guide. The filter is a
  substring of the topic-folder name under the help root.
- Progressive broadening: if `"k-omega sst menter"` returns nothing, try
  `"k-omega sst"`, then `"omega sst"`.

Common topic folders:

| `--module`  | Contents                                   |
|-------------|--------------------------------------------|
| `flu_ug`    | Fluent User's Guide                        |
| `flu_th`    | Theory Guide                               |
| `flu_tg`    | Tutorial Guide                             |
| `flu_udf`   | UDF Manual                                 |
| `flu_ml`    | Meshing Manual                             |
| `pyfluent`  | PyFluent API docs (when bundled on disk)   |

Examples:

```bash
# Physics / theory — Theory Guide
uv run --project <sim-skills>/fluent/doc-search sim-fluent-doc search "k-omega sst" --module flu_th

# UDF macros
uv run --project <sim-skills>/fluent/doc-search sim-fluent-doc search "define_profile" --module flu_udf

# Meshing workflow
uv run --project <sim-skills>/fluent/doc-search sim-fluent-doc search "watertight workflow" --module flu_ml
```

To read the full text of a hit:

```bash
uv run sim-fluent-doc retrieve flu_ug/flu_ug_turbulence.html
```

See `doc-search/README.md` for discovery details and the install-root
override (`--ansys-root`) if auto-detection fails.

### `skill_tests/` and `tests/` (top-level, QA-only)

Not loaded during a normal session. These are natural-language and
pytest test cases used to validate the skill end-to-end against real
Fluent.

---

## Fluent-specific hard constraints

These add to — do not replace — the shared skill's hard constraints.

1. **Never call `pyfluent.launch_fluent()` from a snippet.** sim-cli
   already started the Fluent process. A second `launch_fluent()` call
   spawns a conflicting instance.
2. **Mode cannot change mid-session.** Meshing vs solver is chosen at
   `sim connect --mode …` time. To change modes, disconnect and
   reconnect.
3. **Meshing dependency chain is strict.** The watertight workflow
   requires `InitializeWorkflow → ImportGeometry → LocalSizing →
   SurfaceMesh → DescribeGeometry → UpdateBoundaries → UpdateRegions →
   BoundaryLayers → VolumeMesh → SwitchToSolver` in order. See
   `base/reference/runtime_patterns.md` for the full Fluent dependency
   rules.

---

## Required protocol (one paragraph)

Follow the shared skill's required protocol for the **persistent
session** model. Fluent-specific steps: after `sim connect --solver
fluent --mode <meshing|solver>` and the Step-0 probe, read the active
task template from `base/reference/task_templates.md`, gather Category
A inputs from the user, then execute incrementally via `sim exec`,
checking `sim inspect last.result` after every step. Use snippets from
`base/snippets/` (translating material-accessor calls per
`sdk/pyfluent-0.37/notes.md` if applicable). After the final step,
evaluate against the relevant checklist in
`base/reference/acceptance_checklists.md`.

For the canonical end-to-end example (EX-01 mixing-elbow), the snippet
sequence is `01_read_case` → `02_mesh_check` → `03_setup_physics` →
`04_setup_material` → `05a_setup_bcs_ex01_ex05` → `06_hybrid_init` →
`07_run_150_iter` → `08a_extract_outlet_temp`, followed by acceptance
evaluation against the EX-01 row of `acceptance_checklists.md`.

---

## GUI actuation

When launched with `ui_mode=gui`, a `gui` object is injected into the
`sim exec` namespace. `/connect` advertises it under
`data.tools = ["gui"]`. See
[`sim-skills/sim-cli/gui/SKILL.md`](../sim-cli/gui/SKILL.md) for the full
API (`gui.find`, `dlg.click`, `dlg.send_text`, `dlg.screenshot`, …).

Fluent-specific dialogs you may want to dismiss or answer:

- **"Question"** — Fluent's generic modal confirmer (overwrite
  prompts, unsaved-changes prompt). Dismiss with
  `gui.find("Question").click("OK")`.
- **"Select File"** — standard Windows file picker used by File >
  Read/Write > Case. Prefer the API path
  (`session.file.read_case(...)`, `session.file.write_case(...)`);
  only drive the dialog manually for demos or when the API path is
  unavailable. See `../sim-cli/gui/snippets/fill_file_save_dialog.py`.
- **"ANSYS Fluent Launcher"** — the pre-session dialog. `sim connect`
  launches Fluent directly past it, so a sim session should not normally
  encounter it.

Always try the programmatic path first (`session.tui.*`,
`solver.settings.*`, `meshing.workflow.*`) — `gui` is for the UI-only
surface the SDK doesn't cover.
