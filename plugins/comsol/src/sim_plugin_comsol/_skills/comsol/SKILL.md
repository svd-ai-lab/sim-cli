---
name: comsol-sim
description: Use when the user asks Codex, Claude Code, ChatGPT-style coding agents, or another AI agent to connect to COMSOL, COMSOL Desktop, or COMSOL Multiphysics through sim-cli. Supports solver checks, shared-desktop server-client GUI collaboration, live session connection, .mph inspection, bounded execution, checkpointing, artifact reporting, and troubleshooting. Do not use for generic COMSOL theory. Do not use Java Shell / ordinary Desktop attach for COMSOL automation; it is a deprecated legacy fallback only.
---

# comsol-sim

This file is the **COMSOL Multiphysics** index. Use the sim runtime/JPype path
for serious model building, solving, inspection, saved `.mph` artifacts, and
reliable live GUI collaboration through `visual_mode=shared-desktop`. Do not
use Java Shell / ordinary Desktop attach for COMSOL automation. It is a
deprecated legacy fallback because GUI automation around Java Shell is unstable
and cannot provide structured execution verification.
Use the offline `.mph` inspection path for saved artifacts when no live COMSOL
session is needed.

This skill is self-contained for COMSOL work. Do not require a separate skill
checkout or an external sim-cli skill. Use this file for the COMSOL workflow,
and load the plugin-bundled references below only when the task needs them.

---

## COMSOL-specific layered content

Choose the control path first:

**Routing rule:** an already-open ordinary COMSOL Desktop is **not** a reason
to choose Java Shell. For any serious model build,
reproduction, solve, sweep, checkpointed artifact, or task where Codex needs
structured verification, start or attach through the sim runtime in
`visual_mode=shared-desktop`. The existing standalone Desktop may stay open for
screenshots or reference, but it is not the live server-client model unless
`session.health` confirms `effective_ui_mode="shared-desktop"`,
`ui_capabilities.model_builder_live=true`, and a valid `active_model_tag`.
If the user explicitly refuses server-client mode, pause and explain that the
Java Shell fallback is deprecated and not accepted evidence for serious
automation.

| Path | Use it for | Avoid it for |
|---|---|---|
| sim runtime / JPype | Building, solving, inspecting, debugging, saving `.mph`, repeatable case generation, and reliable live GUI co-editing with `visual_mode=shared-desktop`. | Only avoid when the user explicitly refuses a server-backed/shared Desktop session. |
| **`comsolcompile` + `comsolbatch`** | **Sandboxed one-shot Java workflows: write a `.java` file with `public static Model run()`, compile to `.class`, run with `comsolbatch.exe -nosave`. Used by sim-benchmark trials when sim CLI isn't available.** | **Anything stateful or interactive — prefer sim runtime when available.** |
| saved `.mph` inspection | Offline summaries, archive diffs, and artifact review without starting COMSOL. | Mutating live model state. |

**Hard rule for the `comsolcompile` path** — Java code MUST use chain-style
`model.X("tag").Y("tag2")...` calls. There is NO public `Component`,
`Geometry`, `HeatTransfer`, etc. type — writing `Component comp = ...`
gets `cannot be resolved to a type` from `comsolcompile`. Read
[`base/reference/java_batch_patterns.md`](base/reference/java_batch_patterns.md)
BEFORE writing your `.java`.

For the sim runtime, start with `uv run sim check comsol`, then
`uv run sim connect --solver comsol`, then inspect `session.health`. When the user
wants to watch the live Model Builder while the agent builds or solves, use:

```bash
uv run sim connect --solver comsol --ui-mode gui --driver-option visual_mode=shared-desktop
uv run sim inspect session.health
```

Confirm `ui_capabilities.model_builder_live: true`,
`active_model_tag`, and `live_model_binding.ok: true` before treating the GUI
as synchronized with agent edits. The returned `session.versions` payload tells
you which COMSOL-specific subfolders to load:

```json
"session.versions": {
  "profile":             "mph_1_2_comsol_6_4",
  "active_sdk_layer":    null,        // single SDK line (mph 1.x), no overlay
  "active_solver_layer": "6.4"        // or "6.2" / "6.1" / "6.0"
}
```

There is no `sdk/` overlay because all supported COMSOL versions pin a
single `mph` line (1.2.x). Always read `base/`, then your active
`solver/<slug>/`.

### `base/` — always relevant

| Path | What's there |
|---|---|
| `base/workflows/block_with_hole/` | Steady-state thermal of a heated block with a cylindrical hole. 6 numbered Python steps (`00_create_geometry.py` … `05_plot_temperature.py`). The smallest plugin-owned smoke/reference workflow for this driver. |
| `base/workflows/model_review_loop.md` | Required checkpoint loop for geometry, materials, physics, mesh, study, and results. Use this before continuing after each meaningful edit. |
| `base/workflows/debug_failed_exec.md` | Failure triage loop for a failed `uv run sim exec`: inspect `last.result`, inspect live model state, inspect suspicious node properties, then retry with the smallest patch. |
| `base/reference/runtime_introspection.md` | Live-session inspection contract: preferred `uv run sim inspect` targets, compatibility rules, partial results, and raw Java fallbacks. |
| `base/reference/java_api_patterns.md` | Stable Java API probing patterns: tags first, properties before `set`, selection checks, and version-safe try/except snippets. |
| `base/reference/java_batch_patterns.md` | **Read this BEFORE writing `.java` for `comsolcompile`.** Chain-style call rule, anti-patterns that fail to compile, source-property toggles (`<prop>_src`), study/sol skeleton, KPI extraction via stdout, error triage. |
| `base/reference/mph_file_format.md` | `.mph` is a ZIP archive — internal layout, the three `nodeType` variants (compact/solved/preview), the Global Parameter `T="33"` contract, and the stdlib `mph_inspect` reader. Read this when you need to introspect a `.mph` *without* spinning up `comsolmphserver`. |
| `base/reference/offline_postprocessing_exports.md` | Optional pattern for COMSOL-free/Python postprocessing after a solve. Use when the user asks for reusable result artifacts, full-domain VTU field exports, CSV tables, or postprocessing without keeping COMSOL open. |

Larger engineering examples do not live in this plugin skill. Keep this
plugin-owned content focused on the driver protocol, live introspection,
debug loops, and the smallest smoke/reference workflow.

Each numbered step is a self-contained snippet for the sim runtime after
`uv run sim connect --solver comsol`. Do not translate these steps to Java
Shell; use the sim runtime so execution status, inspect targets, and saved
artifacts are available.

Before running a new or complex workflow, read
[`base/reference/runtime_introspection.md`](base/reference/runtime_introspection.md)
and
[`base/workflows/model_review_loop.md`](base/workflows/model_review_loop.md).
For failed snippets, switch immediately to
[`base/workflows/debug_failed_exec.md`](base/workflows/debug_failed_exec.md)
instead of guessing another full script.

### `solver/<active_solver_layer>/` — release specifics

Empty stubs by default; per-release deltas land here as discovered.

- `solver/6.4/notes.md` — current
- `solver/6.2/notes.md`
- `solver/6.1/notes.md`
- `solver/6.0/notes.md`

### `doc-search/` — local documentation lookup

When a physics feature name, API method, or module capability is unknown,
do **not** guess. Inspect the live model first:

```bash
uv run sim inspect session.health
uv run sim inspect last.result
uv run sim inspect comsol.model.describe_text
uv run sim inspect comsol.node.properties:<tag-or-dot-path>
```

The COMSOL driver may not expose every inspect target on older plugin
builds. If an inspect target is unavailable, use the raw Java fallback
patterns in
[`base/reference/java_api_patterns.md`](base/reference/java_api_patterns.md).
Only after live introspection is insufficient, query the local COMSOL
documentation that ships with every install:

```bash
uv run --project src/sim_plugin_comsol/_skills/comsol/doc-search sim-comsol-doc search "<term>" [--module <substring>]
```

`doc-search` runs in pure CPython: no live COMSOL session, no sim runtime,
and no JVM. It scans the installed COMSOL HTML help on disk.

One-time setup on any host that has COMSOL installed:

```bash
cd src/sim_plugin_comsol/_skills/comsol/doc-search && uv sync
```

(No index build step — each query scans the doc tree in parallel; typical
latency is 1–3 s on a local SSD.)

Tips for good queries:
- Use **2–3 keywords**, not questions. COMSOL search is keyword-matched.
- Filter by `--module battery` / `--heat` / `--cfd` / `--plasma` to bias
  toward a module's plugin folder (matched as a substring of the
  `com.comsol.help.*` name).
- Progressive broadening: if `"C-rate battery"` returns nothing, try
  `"discharge rate"`, then `"battery performance"`.
- For **API / coding** questions, filter `--module programming` or
  `--module api`. Plugin names follow `com.comsol.help.*` — inspect a
  few results and adjust.

To read the full text of a hit:

```bash
uv run sim-comsol-doc retrieve com.comsol.help.battery/battery_aging.03.01.html
```

See `doc-search/README.md` for discovery details and the install-root
override (`--comsol-root`) if auto-detection fails.

#### Application Gallery: local vs. web

The local index also covers the **Application Gallery** content for every
module the user has installed — those plugins are named
`com.comsol.help.models.*` (e.g. `com.comsol.help.models.battery.li_battery_1d`).
Filter with `--module models` to scope a search to example-model docs:

```bash
uv run sim-comsol-doc search "thermal runaway" --module models.battery
```

For models that belong to **modules not installed** on the user's host
(or for browsing by image/category), point the user at
<https://www.comsol.com/models>. Don't scrape it from the skill — just
link.

---

## MPH file introspection (stdlib path — no JVM)

For "what's in this `.mph`?" queries — parameters, physics tags,
nodeType, mesh/solution sizes — prefer the stdlib reader over a live
JVM:

```python
from sim_plugin_comsol.lib import inspect_mph
summary = inspect_mph(path)   # one-shot dict
```

`MphArchive` (context manager) and `mph_diff` (two-file delta) are
also available. `MphFileProbe` is wired into the driver's default
probe list, so any `.mph` produced by a `sim` run is auto-described
in `uv run sim inspect last.result` — no extra call needed.

See [`base/reference/mph_file_format.md`](base/reference/mph_file_format.md)
for the archive layout, the `nodeType` variants, and the Global
Parameter `T="33"` extraction contract.

Use `.mph` archive inspection for saved artifacts and offline comparison.
Use live runtime introspection for the current JPype session, especially
before changing selections, physics features, studies, and result nodes.

## Optional offline postprocessing exports

When the user wants Python-friendly postprocessing without keeping COMSOL
open, export reusable data artifacts once from the live or headless COMSOL
session, then process those files offline. Prefer full-domain VTU field data
and CSV/TXT tables over screenshots or slices as the reusable source data.

See
[`base/reference/offline_postprocessing_exports.md`](base/reference/offline_postprocessing_exports.md)
for the optional bundle layout and headless export snippets.

---

## Headless `comsolbatch` (not yet implemented)

`comsolbatch.exe -inputfile in.mph -outputfile out.mph -batchlog log.txt`
is the canonical non-interactive entry point and would let an agent
run saved models without the long-lived `comsolmphserver` setup. The
driver currently always goes through `comsolmphserver` + JPype. When a
one-shot `comsolbatch` path is available, prefer it for deterministic saved
model batch runs that do not need Desktop collaboration or live introspection.

---

## COMSOL-specific hard constraints

These hard constraints apply to every COMSOL task through this plugin.

1. **Never call `mph.start()` or `client.create()` from a snippet.**
   sim-cli already started a COMSOL JVM and gave you a `model` handle.
   A second `start()` spawns a conflicting JVM.
2. **Image export is broken on Windows.** Use the inspection helpers
   referenced in the workflow READMEs (slice / probe extraction →
   numeric review) instead of `model.result().export()` PNGs. The
   Numeric probes and exported data are more reliable for reviewing results.
3. **Never hardcode COMSOL property names before inspecting the live
   node.** Prefer `uv run sim inspect comsol.node.properties:<target>` or the
   raw Java `properties()` pattern before calling `set(...)`.
4. **Do not run long monolithic model builders.** Build one bounded
   model layer, inspect the live state, then continue.

---

## Model identity, workdir, and checkpoints

For non-trivial COMSOL work, establish a durable model identity and working
folder before building geometry, materials, physics, mesh, or studies.
COMSOL permits untitled `Model1` scratch models, but agents need a clear
artifact to resume from after chat compaction, process restart, server reload,
or human handoff.

Use this policy:

- Do not build serious geometry, materials, physics, meshes, studies, sweeps,
  or results in `Untitled.mph` or an unnamed `Model1`. The first real modeling
  step is to create or bind a durable project identity, set a visible
  title/label, set the working folder, and save an initial `.mph` checkpoint.
- If the user provided an `.mph`, load that exact file and bind the session to
  a clear model tag derived from the case name.
- If starting from scratch in the sim runtime, pass a descriptive
  `model_tag=<case_slug>` when connecting if the current driver supports it.
- If starting from scratch in shared Desktop mode, bind to the active Desktop
  model first, then set a visible title/label and save it early to an absolute
  `.mph` path.
- Keep all related files under one working folder, for example:

```text
<workdir>/
  model/<case_slug>.mph
  input/
  output/
  scripts/
  logs/
```

- Set `model.modelPath(...)` to the relevant `input` and `model` folders
  when the workflow uses external files, tables, meshes, or CAD.
- Prefer absolute paths for save/export/log targets. Do not rely on COMSOL's
  launch directory or the Java process current directory.
- After every major layer, save a checkpoint `.mph` or save the main `.mph`
  after confirming the live state. Use names such as
  `<case_slug>_01_geometry.mph`, `<case_slug>_02_materials.mph`, and
  `<case_slug>_03_solved.mph` when intermediate files help review or resume.
- Before resuming a partially completed task, inspect identity first:

```bash
uv run sim inspect session.health
uv run sim inspect comsol.model.identity
uv run sim inspect comsol.model.describe_text
```

Treat `comsol.model.identity.checkpoint_ready=false`, missing
`file_path`/`location`, or a bound tag that does not match `active_model_tag`
as a pause-and-repair condition before doing new modeling work. Repair means
creating or binding the intended project, setting the model path, and saving an
initial `.mph`; do not "just continue" in the untitled session.

Scratch probes and one-off API experiments may stay as `Model1` or
`Untitled.mph`, but label them as disposable in the agent's status and do not
mix them with user-facing engineering artifacts. If a scratch probe turns into
real work, stop and rebuild it under a named project rather than letting the
untitled session become the deliverable.

---

## Required protocol

Treat COMSOL as a live engineering state, not as a one-shot code generator.
Most user-facing sessions are human-in-the-loop Desktop sessions; keep the
visible model coherent after every step.

COMSOL's Java API is stateful and layered. Many `set(...)` calls mutate the
model tree, but downstream objects and the Desktop view may not reflect those
changes until the relevant sequence is built or run. Use `run()` calls as
intentional synchronization points when the next step depends on updated state
or when the user expects the Model Builder / Graphics view to be current. Do
not make this mechanical: batch coherent edits first, then choose the smallest
appropriate build/run for the layer you changed (for example geometry, mesh,
plot, study, or solver). The goal is to understand and respect COMSOL's
commit/refresh mechanism, not to force a fixed `run()` after every property
assignment.

0. If the question is about a saved `.mph` (parameters, physics tags,
   solved/unsolved state, mesh size), use `inspect_mph(path)` first — no
   JVM and no `uv run sim connect` needed. Skip to step 1 only if the model needs
   to be mutated or solved.
1. Choose the control path. Default to the sim runtime for reliable model
   building, solving, and live GUI collaboration:
   - Use `uv run sim connect --solver comsol --ui-mode gui --driver-option
     visual_mode=shared-desktop` when the user wants real-time Model Builder
     visibility and the agent needs structured `uv run sim inspect`/JPype state.
   - Use plain `uv run sim connect --solver comsol` for no-GUI/server execution,
     driver-managed artifacts, and existing sim runtime workflows.
   - If the user says COMSOL is already open, treat that as visual context only.
     Do not infer that Java Shell is preferred; ask whether to preserve unsaved
     standalone Desktop edits only if needed, then proceed with
     `shared-desktop` for serious work.
2. For sim runtime, run `uv run sim check comsol`, connect if needed, and read
   `session.versions` plus `uv run sim inspect session.health`.
3. Establish or verify model identity, working folder, and checkpoint target.
   Inspect `comsol.model.identity` when available. If the model is untitled,
   unsaved, missing a file path, or lacks the intended working folder, fix that
   before creating geometry, materials, physics, mesh, study, or result nodes.
4. Inspect the baseline state with `uv run sim inspect
   comsol.model.describe_text` when available.
5. Execute one bounded modeling step.
6. Inspect the result before continuing with `uv run sim inspect last.result`,
   `comsol.model.describe_text`, and
   `comsol.node.properties:<tag-or-dot-path>` as needed.
7. Save or update the relevant checkpoint after each passed major layer.
8. Continue only after the live model matches the intended geometry,
   materials, physics, mesh, study, and result state and the checkpoint can be
   used to resume.

For simple known-good smoke coverage, use the numbered snippets under
`base/workflows/`. For realistic engineering examples, use project-local
or user-provided recipes and apply the same checkpoint loop.

---

## GUI and visual inspection modes

COMSOL has several visual surfaces. Do not collapse them into one
"GUI mode" in your reasoning or status reports:

| Mode | What it means | Live with agent edits? |
|---|---|---|
| `no_gui` | `comsolmphserver` API session with no intentional visible windows. This is the canonical sim-cli default. | Yes, API session only. |
| `server-graphics` | `comsolmphserver -graphics`; plot windows may appear when a result plot is run. `ui_mode=gui` is an alias for this. | Yes for the server-side model, but there is no Model Builder tree. |
| `desktop-inspection` | Save a `.mph` artifact, then open it in full COMSOL Desktop / Model Builder. | No. It is an inspection copy unless explicitly reloaded. |
| `shared-desktop` | Full COMSOL Desktop attached to the same server, with the agent binding to the Desktop's active model tag. Request from sim-cli with `--driver-option visual_mode=shared-desktop`. | Yes, when `model_builder_live: true`. |
| `desktop-attach` | Deprecated legacy Java Shell UIA fallback for an already-open ordinary Desktop. Do not use for automation. | Not accepted for serious agent work because it lacks structured verification and is GUI-fragile. |

Use `uv run sim inspect session.health` or `uv run sim exec` target `session.health`
to check `requested_ui_mode`, `effective_ui_mode`, `ui_capabilities`,
PIDs, logs, and visible COMSOL window titles. Treat `model_builder_live:
false` as authoritative: agent-side JPype edits will not automatically
refresh a separately opened COMSOL Desktop window.

### Deprecated legacy: Java Shell / ordinary Desktop attach

Do not use `sim-comsol-attach` or Java Shell for COMSOL automation. The path is
too GUI-fragile and reports submission, not verified execution. Keep it out of
normal agent workflows, reproduction work, long model builders, solves,
screenshots-as-proof, and validation. If a legacy troubleshooting task names
`sim-comsol-attach` explicitly, state that it is deprecated, keep the action
read-only or very small, and do not treat it as acceptance evidence. Prefer
server-client `shared-desktop` instead.

Shared-desktop gotcha for COMSOL 6.4: launching
`comsol.exe mphclient -host localhost -port <port>` does attach a full
Desktop to `comsolmphserver`. However, if JPype creates a separate
server model tag with `ModelUtil.create("SharedProbe")`, the Desktop
does not automatically switch from its active `Model1` tree to that
new tag. When JPype instead mutates `ModelUtil.model("Model1")`, the
Desktop refreshes: the title, Model Builder tree, and Graphics view
show the API-created component/geometry. The implemented
`shared-desktop` mode therefore discovers or negotiates the active
Desktop model tag and routes agent edits to that tag.

Use:

```powershell
uv run sim connect --solver comsol --ui-mode gui --driver-option visual_mode=shared-desktop
```

Then verify `session.health`: `effective_ui_mode` should be
`shared-desktop`, `ui_capabilities.model_builder_live` should be `true`,
and `active_model_tag` should name the model that agent snippets will
mutate.

### Attach-only external server

If repeated API client disconnects occur, or a user wants one COMSOL
server to survive multiple sim sessions, use an externally managed server
instead of mixing sim and ad hoc JPype scripts. The user or agent starts
`comsolmphserver` first in an interactive Windows shell:

```powershell
& "C:\Program Files\COMSOL\COMSOL64\Multiphysics\bin\win64\comsolmphserver.exe" -port 2036 -multi on -login auto -silent
```

Then connect through sim with explicit attach-only ownership:

```powershell
uv run sim connect --solver comsol --ui-mode gui `
  --driver-option attach_only=true `
  --driver-option port=2036 `
  --driver-option visual_mode=shared-desktop
```

In attach-only mode, `session.health` should show
`server_owner: "external"` and `attach_only: true`. `uv run sim disconnect`
disconnects the JPype client and any plugin-launched Desktop client, but
does not kill the external `comsolmphserver`. Keep all agent operations
inside the sim session; use ad hoc JPype only as a diagnostic escape hatch.

### Screenshot responsibility

On a Codex Desktop host with access to the interactive solver GUI, prefer Codex's own desktop
screenshot/view tools for visual review. They see the same
interactive desktop the user sees and avoid adding solver-specific
screenshot commands to sim-cli. Use `uv run sim screenshot` only when the
solver GUI is on a remote host that Codex cannot directly capture.

When you perform GUI-visible work, review the Desktop state after every significant action:

1. Launch or connect.
2. Geometry build or import.
3. Material assignment.
4. Physics setup.
5. Mesh build.
6. Solve and result plot.
7. Save/open `.mph` for Desktop inspection when Model Builder review is needed.

### COMSOL-specific dialogs

- **"连接到 COMSOL Multiphysics Server"** / **"Connect to COMSOL
  Multiphysics Server"** may be a stale or separate Desktop/client
  login dialog. It does not prove the JPype server session failed.
  Verify by checking `session.health`, the port, PIDs, and visible
  window titles.
- **"是否保存更改?"** / **"Save changes?"** appears on Desktop close if
  a separately opened `.mph` has unsaved edits. Choose Save or Don't Save
  according to the user's intent.

Prefer the JPype path (`model.*`, `ModelUtil.*`) for programmable model
construction and solving. Use Desktop inspection only when a human needs
to see the Model Builder tree or interact with file/dialog surfaces.
