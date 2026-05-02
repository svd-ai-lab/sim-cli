---
name: comsol-sim
description: Use when working with COMSOL Multiphysics through the sim runtime or inspecting saved `.mph` artifacts — building, inspecting, debugging, and solving stateful COMSOL models through the JPype Java API, optionally with a human watching the COMSOL GUI client, plus offline `.mph` introspection without a JVM.
---

# comsol-sim

This file is the **COMSOL Multiphysics** index. Use the offline `.mph`
inspection path for saved artifacts; use sim-cli for persistent live sessions
that mutate, solve, or inspect the current JPype Java API model.

> **First, read [`../sim-cli/SKILL.md`](../sim-cli/SKILL.md)** — it owns
> the shared runtime contract (session lifecycle, Step-0 version probe,
> input classification, acceptance, escalation). This skill covers only
> the COMSOL-specific layer on top of that contract.

---

## COMSOL-specific layered content

After `sim connect --solver comsol` and the shared-skill Step-0 probe,
the returned `session.versions` payload tells you which COMSOL-specific
subfolders to load:

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
| `base/workflows/debug_failed_exec.md` | Failure triage loop for a failed `sim exec`: inspect `last.result`, inspect live model state, inspect suspicious node properties, then retry with the smallest patch. |
| `base/reference/runtime_introspection.md` | Live-session inspection contract: preferred `sim inspect` targets, compatibility rules, partial results, and raw Java fallbacks. |
| `base/reference/java_api_patterns.md` | Stable Java API probing patterns: tags first, properties before `set`, selection checks, and version-safe try/except snippets. |
| `base/reference/mph_file_format.md` | `.mph` is a ZIP archive — internal layout, the three `nodeType` variants (compact/solved/preview), the Global Parameter `T="33"` contract, and the stdlib `mph_inspect` reader. Read this when you need to introspect a `.mph` *without* spinning up `comsolmphserver`. |

Larger engineering examples do not live in this plugin skill. Keep this
plugin-owned content focused on the driver protocol, live introspection,
debug loops, and the smallest smoke/reference workflow.

Each numbered step is a self-contained snippet you submit via
`sim exec` after `sim connect --solver comsol`. The snippets use the
injected `model` object — they do NOT call `mph.start()` or open a
client of their own.

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
sim inspect session.health
sim inspect last.result
sim inspect comsol.model.describe_text
sim inspect comsol.node.properties:<tag-or-dot-path>
```

The COMSOL driver may not expose every inspect target on older plugin
builds. If an inspect target is unavailable, use the raw Java fallback
patterns in
[`base/reference/java_api_patterns.md`](base/reference/java_api_patterns.md).
Only after live introspection is insufficient, query the local COMSOL
documentation that ships with every install:

```bash
uv run --project <sim-skills>/comsol/doc-search sim-comsol-doc search "<term>" [--module <substring>]
```

`doc-search` runs in pure CPython: no live COMSOL session, no sim runtime,
and no JVM. It scans the installed COMSOL HTML help on disk.

One-time setup on any host that has COMSOL installed:

```bash
cd <sim-skills>/comsol/doc-search && uv sync
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
in `sim inspect last.result` — no extra call needed.

See [`base/reference/mph_file_format.md`](base/reference/mph_file_format.md)
for the archive layout, the `nodeType` variants, and the Global
Parameter `T="33"` extraction contract.

Use `.mph` archive inspection for saved artifacts and offline comparison.
Use live runtime introspection for the current JPype session, especially
before changing selections, physics features, studies, and result nodes.

---

## Headless `comsolbatch` (not yet implemented)

`comsolbatch.exe -inputfile in.mph -outputfile out.mph -batchlog log.txt`
is the canonical non-interactive entry point and would let an agent
smoke-test models without the long-lived `comsolmphserver` setup. The
driver currently always goes through `comsolmphserver` + JPype.
Tracked in [sim-proj#51](https://github.com/svd-ai-lab/sim-proj/issues/51)
/ [sim-cli#47](https://github.com/svd-ai-lab/sim-cli/pull/47); when it
lands the workflow snippets above will pick up a one-shot path that
skips GUI actuation entirely.

---

## COMSOL-specific hard constraints

These add to — do not replace — the shared skill's hard constraints.

1. **Never call `mph.start()` or `client.create()` from a snippet.**
   sim-cli already started a COMSOL JVM and gave you a `model` handle.
   A second `start()` spawns a conflicting JVM.
2. **Image export is broken on Windows.** Use the verification helpers
   referenced in the workflow READMEs (slice / probe extraction →
   numeric acceptance) instead of `model.result().export()` PNGs. The
   shared skill's `acceptance.md` explains why numeric acceptance
   beats visual acceptance anyway.
3. **Never hardcode COMSOL property names before inspecting the live
   node.** Prefer `sim inspect comsol.node.properties:<target>` or the
   raw Java `properties()` pattern before calling `set(...)`.
4. **Do not run long monolithic model builders.** Build one bounded
   model layer, inspect the live state, then continue.

---

## Required protocol

COMSOL through sim is a persistent, inspectable modeling session. Treat
it as a live engineering state, not as a one-shot code generator.

0. If the question is about a saved `.mph` (parameters, physics tags,
   solved/unsolved state, mesh size), use `inspect_mph(path)` first — no
   JVM and no `sim connect` needed. Skip to step 1 only if the model needs
   to be mutated or solved.
1. Choose the control path. For interactive Windows work, default to the
   human-collaboration path unless the task explicitly needs the driver
   runtime:
   - Use the standalone Desktop attach helper when the user wants ordinary,
     realtime-visible COMSOL Desktop work, when they already opened Desktop,
     or when avoiding the `mphclient` server login dialog matters.
   - Use `sim connect --solver comsol` only when you need `sim inspect`,
     JPype session state, driver-managed artifacts, headless/server
     execution, or compatibility with existing sim runtime workflows.
2. Run the shared Step-0 version probe and read `session.versions`.
3. Inspect `sim inspect session.health`.
4. Inspect the baseline model with `sim inspect comsol.model.describe_text`
   when available.
5. Execute one bounded modeling step with `sim exec`.
6. Inspect `sim inspect last.result`.
7. Inspect the changed model state with
   `sim inspect comsol.model.describe_text` and, when needed,
   `sim inspect comsol.node.properties:<tag-or-dot-path>`.
8. Continue only after the live model matches the intended geometry,
   materials, physics, mesh, study, and result state.

For simple known-good smoke coverage, use the numbered snippets under
`base/workflows/`. For realistic engineering examples, use project-local
or user-provided recipes and apply the same checkpoint loop.

---

## GUI and visual inspection modes

COMSOL has several visual surfaces. Do not collapse them into one
"GUI mode" in your reasoning or status reports:

| Mode | What it means | Live with agent edits? |
|---|---|---|
| `headless` | `comsolmphserver` API session with no intentional visible windows. | Yes, API session only. |
| `server-graphics` | `comsolmphserver -graphics`; plot windows may appear when a result plot is run. This is the current default effective mode. Legacy `ui_mode=gui` is an alias for this. | Yes for the server-side model, but there is no Model Builder tree. |
| `desktop-inspection` | Save a `.mph` artifact, then open it in full COMSOL Desktop / Model Builder. | No. It is an inspection copy unless explicitly reloaded. |
| `shared-desktop` | Full COMSOL Desktop attached to the same server, with the agent binding to the Desktop's active model tag. Request from sim-cli with `--driver-option visual_mode=shared-desktop`. | Yes, when `model_builder_live: true`. |
| `desktop-attach` | Ordinary COMSOL Desktop, controlled through the Java Shell UIA channel via `sim-comsol-attach`. No `mphclient`, no shared server login dialog. | Yes, in the visible Desktop model, but without `sim inspect`/JPype session introspection. |

Use `sim inspect session.health` or `sim exec` target `session.health`
to check `requested_ui_mode`, `effective_ui_mode`, `ui_capabilities`,
PIDs, logs, and visible COMSOL window titles. Treat `model_builder_live:
false` as authoritative: agent-side JPype edits will not automatically
refresh a separately opened COMSOL Desktop window.

### Ordinary Desktop attach helper

For interactive Windows work, the normal user-facing default is the
standalone helper:

```powershell
sim-comsol-attach open --json --timeout 120
sim-comsol-attach health --json
sim-comsol-attach exec --file step.java --json
```

`open` launches normal `comsol.exe` if no suitable Desktop exists,
clicks Blank Model when needed, opens Java Shell, and waits for a
`SyntaxEditor` input. It does not launch `comsol.exe mphclient`, so it
avoids the repeated "Connect to COMSOL Multiphysics Server" dialog.

For `exec`, submit bounded Java Shell snippets that use COMSOL's Java API
against the visible Desktop model. Keep the same modeling discipline as
`sim exec`: one layer at a time, verify the Desktop after each geometry,
material, physics, mesh, solve, and plot step, then continue. The helper
audits submissions under `.sim/comsol-desktop-attach/audit.jsonl`.

By default, `exec` rejects arbitrary Java lines that do not start from the
COMSOL model surface. Use `--allow-arbitrary-java` only for deliberate
diagnostic snippets. If you need structured model introspection, saved
artifacts, or cross-session runtime state, switch back to the driver path
with `sim connect --solver comsol`.

Shared-desktop gotcha verified on Win1 with COMSOL 6.4: launching
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
sim connect --solver comsol --ui-mode gui --driver-option visual_mode=shared-desktop
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
sim connect --solver comsol --ui-mode gui `
  --driver-option attach_only=true `
  --driver-option port=2036 `
  --driver-option visual_mode=shared-desktop
```

In attach-only mode, `session.health` should show
`server_owner: "external"` and `attach_only: true`. `sim disconnect`
disconnects the JPype client and any plugin-launched Desktop client, but
does not kill the external `comsolmphserver`. Keep all agent operations
inside the sim session; use ad hoc JPype only as a diagnostic escape hatch.

### Screenshot responsibility

On a Codex Desktop host such as Win1, prefer Codex's own desktop
screenshot/view tools for visual verification. They see the same
interactive desktop the user sees and avoid adding solver-specific
screenshot commands to sim-cli. Use `sim screenshot` only when the
solver GUI is on a remote host that Codex cannot directly capture.

When you perform GUI-visible work, verify after every significant action:

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
