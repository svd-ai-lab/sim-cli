---
name: abaqus-sim
description: "Use when the user asks Codex, Claude Code, ChatGPT-style coding agents, or another AI agent to automate, inspect, run, or debug Abaqus. Choose the simplest real Abaqus control path first: existing artifacts, direct vendor launchers/batch commands, Abaqus/CAE noGUI, or sim-cli when standardized execution, diagnostics, session handling, and artifact reporting are useful. Requires a user-owned Abaqus installation."
---

# abaqus-sim

This file is the **Abaqus** index. Prefer direct local evidence first: existing
`.inp`/`.odb`/`.dat`/`.sta`/`.msg` artifacts, Abaqus/SIMULIA command launchers,
installed vendor docs, or user-provided paths. Use sim-cli for solver execution
and live CAE authoring when its wrapping adds useful structure.

Abaqus is a commercial finite element analysis (FEA) solver by Dassault
Systemes SIMULIA. The sim plugin supports two execution styles:

1. **Batch execution** for complete `.inp` decks or Abaqus/CAE Python files.
2. **CAE authoring sessions** for iterative model creation, inspection,
   debugging, job submission, and report preparation. The default backend is
   file-backed; the optional bridge backend keeps one noGUI CAE process alive
   for faster agent loops.

It supports two script formats:

- **Input decks** (`.inp`) — keyword-driven text files defining geometry,
  materials, loads, BCs, and analysis steps
- **Abaqus/CAE Python scripts** (`.py`) — Python scripts using the
  `abaqus` and `abaqusConstants` modules for parametric model building

The driver runs these via subprocess (`abaqus job=X input=file.inp
interactive` or `abaqus cae noGUI=script.py`). In CAE authoring sessions,
each `uv run sim exec` snippet runs inside Abaqus/CAE against a saved session `.cae`
database, then saves the database back for the next step. With
`--backend bridge`, snippets are sent to one long-lived noGUI CAE process over
a localhost command channel protected by a per-session token. Use bridge mode
only in trusted workspaces owned by the session user. No Abaqus Python module
is imported into the sim process.

This is **not** the Ansys Mechanical plugin. Do not route Abaqus `.inp`
decks or Abaqus/CAE Python scripts through `solver=mechanical`; use
`solver=abaqus` for Abaqus execution/authoring and `solver=mechanical` only
for PyMechanical / Ansys Mechanical sessions.

---

## base/ — always relevant

| Path | What's there |
|---|---|
| `base/reference/input_deck_reference.md` | `.inp` file format: keyword syntax, node/element definitions, material, steps, BCs, output requests. |
| `base/reference/abaqus_scripting.md` | Abaqus/CAE Python scripting: `mdb`, `Part`, `Material`, `Step`, `Load`, `Job` objects. |
| `base/reference/doc_lookup.md` | How to check installed/official Abaqus docs, command help, fetched examples, and runtime API probes before guessing syntax. |
| `base/reference/authoring_workflow.md` | Agent workflow for iterative CAE modeling with `connect`, `exec`, `inspect`, and saved `.cae` state. |
| `base/reference/debug_reporting.md` | Debug loop and report checklist for `.msg`, `.sta`, `.dat`, ODB-derived results, assumptions, and acceptance criteria. |
| `base/reference/analysis_types.md` | Supported analysis types: Static, Dynamic, Heat Transfer, Coupled, etc. |
| `base/snippets/` | Tested execution snippets (cantilever beam E2E). |
| `base/known_issues.md` | Vendor quirks and workarounds discovered during testing. |

## solver/2026/ — Abaqus 2026 specifics

- `solver/2026/notes.md` — Abaqus 2026 version notes and quirks.

---

## Hard constraints (apply to every session)

0. **Respect the Abaqus embedded-Python boundary.** Ordinary file-side
   plotting/post-processing follows the sim-cli Python-helper environment when
   sim runtime is in use. Abaqus/CAE and ODB scripts are different: execute them
   through a real Abaqus launcher such as `abaqus cae noGUI=script.py`, or
   through `uv run sim run --solver abaqus script.py` when using sim runtime, so
   Abaqus launches its embedded Python with the vendor modules available.
1. **Direct availability first.** Before requiring sim-cli, look for a real
   Abaqus launcher through `SIM_ABAQUS_COMMAND`, `ABAQUS_COMMAND`,
   `ABAQUS_BAT_PATH`, `PATH` entries such as `abaqus`/`abq20*.bat`, and common
   SIMULIA Commands locations such as `C:\SIMULIA\Commands` or
   `C:\Program Files\Dassault Systemes\SIMULIA\Commands`. If sim-cli/plugin is
   already available or needed for deeper runtime validation, run
   `uv run sim check abaqus`. If no direct or sim runtime path is found, ask the
   user for an Abaqus launcher path; do not continue with fake geometry.
2. **Never invent Category A defaults.** Geometry, materials, BCs,
   analysis type, acceptance criteria — if missing, ask the user.
3. **Acceptance != exit code.** Validate against physics-based criteria
   (displacement, stress, temperature ranges), not just `exit_code == 0`.
4. **Input deck keywords are case-insensitive** but use `*UPPERCASE` by
   convention. Always include `*HEADING`.
5. **Working directory matters.** Abaqus creates output files (.dat, .odb,
   .msg, .sta) next to the input file. Use `cwd` appropriately.
6. **Use the right mode.** If the model is already fully specified, prefer
   `uv run sim run --solver abaqus file.inp` or `uv run sim run --solver abaqus script.py`.
   If the agent is building/debugging the model incrementally, use
   `uv run sim connect --solver abaqus --mode cae` and iterate with `uv run sim exec`. Use
   `--backend bridge` when repeated small snippets need a live in-memory CAE
   session.
7. **Save and inspect after every modeling step.** In CAE authoring mode,
   each snippet should leave the `.cae` database in a coherent state and then
   check `uv run sim inspect cae.model_summary` or `uv run sim inspect job.diagnostics`.
8. **Check docs or probe before guessing APIs.** If unsure about an Abaqus
   keyword, CAE method, command option, or output variable, follow
   `base/reference/doc_lookup.md` before editing the real model.
9. **Use a case workspace for non-trivial work.** Do not scatter generated
   scripts, `.cae`, `.odb`, diagnostics, renders, metrics, and reports across
   the shell cwd, temp folders, and chat history. Establish one case or run
   folder before modeling, and keep artifacts in predictable subfolders.

## Case workspace shape

For any non-trivial Abaqus task, establish or verify a durable case workspace
before creating geometry, submitting jobs, rendering results, or writing a
report. A workspace is just a self-contained project folder that a future
agent or human can reopen:

```text
<workdir>/
  model/          # .cae database, named checkpoints, model copies
  input/          # parameters, CAD, source data, user-provided decks
  scripts/        # generated or hand-written Abaqus/CAE and ODB scripts
  run/            # solver-native job outputs: .inp, .odb, .msg, .sta, .dat
  render/         # Abaqus/CAE or Viewer PNG/MP4/viewport evidence
  output/         # metrics JSON, tables, extracted summaries
  report/         # markdown/html/pdf summary when generated
```

Use the user-provided folder when one exists. When starting from scratch,
choose a descriptive slug such as `runs/bracket_static` or
`runs/hole_plate_modal` and pass it as `--workspace` for CAE authoring
sessions. The driver may keep its managed `session.cae` at the workspace root;
save named review checkpoints under `model/` when they help resume or compare
work, for example `model/hole_plate_01_geometry.cae`,
`model/hole_plate_02_mesh.cae`, and `model/hole_plate_03_solved.cae`.

Prefer Abaqus/CAE or Abaqus Viewer for canonical render evidence. `render/`
should contain solver-rendered contour images, deformed-shape views, modal
views, or animations when requested. `output/` should contain machine-readable
metrics and extracted tables. `report/` should reference those artifacts by
path and state which files support each conclusion.

---

## Long-running execution and recovery

Keep bounded Abaqus work in the foreground when it fits the active tool-call
budget. Use a settled input deck, CAE noGUI script, or background process only
when the run is expected to outlive that budget, must continue across agent
turns, or the user explicitly asks for background execution.

For a long run, use a stable job name and absolute working/output paths so the
agent can inspect it later. A shell or tool timeout ends that observation call;
it does not prove Abaqus stopped. Before submitting the same job again, check
the existing launcher/solver process, `.sta` progress, `.msg` and `.dat`
diagnostics, and `.odb` or other expected artifact timestamps.

Confirm process ownership from the job name, executable and full command line,
start time, working directory, and output targets. Prefer Abaqus-native job
cancellation; otherwise stop only the exact confirmed process or process tree.
Never terminate every Abaqus, Standard, or Explicit process by name.

Treat a successful process exit as only one completion signal. Confirm the
Abaqus completion marker and usable expected artifacts before claiming the
analysis completed. Use *resume* only when an Abaqus restart/checkpoint artifact
can actually continue the analysis; without one, describe a new submission as
a restart.

---

## Required protocol

After direct launcher discovery or sim runtime validation confirms a real
Abaqus path is available, gather Category A inputs from the user (geometry,
material properties, loads, BCs, analysis type, acceptance criteria). For
non-trivial work, establish the case workspace above before generating files.

For batch work: write the `.inp` deck or `.py` script, lint with `uv run sim lint`
when sim-cli is part of the chosen runtime, execute through the smallest real
path available (`abaqus job=... input=...`, `abaqus cae noGUI=script.py`, or
`uv run sim run --solver abaqus ...` for sim runtime), then choose the
post-processing path by artifact: `.dat` -> Python text parsing on the fetched
file; ODB -> vendor Python through Abaqus/CAE noGUI or
`uv run sim run --solver abaqus script.py` when using sim runtime. For ordinary
file-side post-processing and plotting, use the host Python environment unless
the sim-cli Python-helper environment is already the selected execution path.
Validate against physics-based acceptance criteria. Keep source decks/scripts
under `input/` or `scripts/`, job products under `run/`, Abaqus-rendered images
or animations under `render/`, and extracted metrics/tables under `output/`.

For modeling/debug/reporting work, choose the smallest real interactive path:
attach to or use Abaqus/CAE directly when the user already has it available, or
start `uv run sim connect --solver abaqus --mode cae --ui-mode no_gui --workspace
<workdir>` when sim session management and inspection surfaces are useful,
optionally adding `--backend bridge` for a live noGUI CAE process. Build the
model in small CAE Python snippets, inspect after each major step, save
checkpoints when useful, submit jobs from the session, read diagnostics, render
canonical views in
Abaqus/CAE or Viewer, fix the model, and produce a report that states
assumptions, units, mesh, BCs, loads, solver messages, result checks,
artifact paths, and acceptance status.
