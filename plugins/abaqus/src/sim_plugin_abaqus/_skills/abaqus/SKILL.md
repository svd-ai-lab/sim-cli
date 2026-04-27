---
name: abaqus-sim
description: Use when driving Dassault Systemes SIMULIA Abaqus via input decks (.inp) or Abaqus/CAE Python scripts — static/dynamic/thermal FEA through sim runtime one-shot execution.
---

# abaqus-sim

You are connected to **Abaqus** via sim-cli. This file is the
**index**. It tells you where to look for actual content — it does not
contain the content itself.

Abaqus is a commercial finite element analysis (FEA) solver by Dassault
Systemes SIMULIA. It supports two script formats:

- **Input decks** (`.inp`) — keyword-driven text files defining geometry,
  materials, loads, BCs, and analysis steps
- **Abaqus/CAE Python scripts** (`.py`) — Python scripts using the
  `abaqus` and `abaqusConstants` modules for parametric model building

The driver runs these via subprocess (`abaqus job=X input=file.inp
interactive` or `abaqus cae noGUI=script.py`). No Python SDK is imported
into the sim process.

---

## base/ — always relevant

| Path | What's there |
|---|---|
| `base/reference/input_deck_reference.md` | `.inp` file format: keyword syntax, node/element definitions, material, steps, BCs, output requests. |
| `base/reference/abaqus_scripting.md` | Abaqus/CAE Python scripting: `mdb`, `Part`, `Material`, `Step`, `Load`, `Job` objects. |
| `base/reference/analysis_types.md` | Supported analysis types: Static, Dynamic, Heat Transfer, Coupled, etc. |
| `base/snippets/` | Tested execution snippets (cantilever beam E2E). |
| `base/known_issues.md` | Vendor quirks and workarounds discovered during testing. |

## solver/2026/ — Abaqus 2026 specifics

- `solver/2026/notes.md` — Abaqus 2026 version notes and quirks.

---

## Hard constraints (apply to every session)

1. **Never invent Category A defaults.** Geometry, materials, BCs,
   analysis type, acceptance criteria — if missing, ask the user.
2. **Acceptance != exit code.** Validate against physics-based criteria
   (displacement, stress, temperature ranges), not just `exit_code == 0`.
3. **Input deck keywords are case-insensitive** but use `*UPPERCASE` by
   convention. Always include `*HEADING`.
4. **Working directory matters.** Abaqus creates output files (.dat, .odb,
   .msg, .sta) next to the input file. Use `cwd` appropriately.

---

## Required protocol

After `sim check abaqus` confirms the solver is available: gather
Category A inputs from the user (geometry, material properties, loads,
BCs, acceptance criteria). Write the `.inp` input deck or `.py` script.
Lint with `sim lint`. Execute with `sim run --solver abaqus`. Parse
results from `.dat` output. Validate against physics-based acceptance
criteria.
