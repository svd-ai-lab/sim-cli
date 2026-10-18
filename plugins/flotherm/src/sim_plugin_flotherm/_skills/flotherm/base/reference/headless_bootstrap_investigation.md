# Headless authoring + library lookup — what we ruled out, what's still open

This page records the closed and open questions from the 2026-04-27 reverse-engineering experiments. It's not a how-to — it's a "don't repeat these probes" map for future agents.

## Background

Two long-standing pain points blocked fully-headless Flotherm authoring on 2504:

1. **Headless project authoring** — `flotherm.bat -b` is broken (ISSUE-001). Direct `translator.exe` + `solexe.exe` re-solves an existing project but can't *create* one. The intermediate `flogate_cl` chain (`FloXML → PDML → floimport`) produces a project shell that translator silently no-ops on.
2. **`<load_from_library>` returns `E/15001`** regardless of the `<library_name>` form tried (ISSUE-006). The path was an "open question" in `playbook.md` for weeks.

Both were probed in the 2026-04-27 batch.

---

## Closed: overlay onto a working scaffold is *not* viable

**Hypothesis.** Take a solved donor project (Mobile_Demo). Overwrite only `PDProject/group` with a new model's PDML (built via `flogate_cl -iFloXML -oPDML`). Keep the donor's `DataSets/BaseSolution/` directories and let translator re-translate against the new model, reusing the existing scaffolding.

**Result.** Translator crashes with **`STATUS_STACK_BUFFER_OVERRUN`** (`0xC0000409`) at offset `0x1cba8` in `ucrtbase.dll`. The Windows Application Event Log captures it as a faulting application crash; nothing reaches `floerror.log`.

**What this proves:**

- ✅ **`PDProject/group` *is* read by translator.** That was an open question — the crash empirically settles it. Translator is not blind to the file.
- ❌ **You cannot reuse a solved project's `DataSets/BaseSolution/` with a different model's `PDProject/group`.** The mesh-geometry mismatch tickles a runtime stack-buffer guard. It's the first time we've ever seen translator produce a *loud* error on a FloXML-authored project — previously it just silently no-op'd.
- ⚠️ **The `flopdupdate` / `floupdateall` / `flocatalogue` chain has undocumented arg requirements.** The piecemeal invocations I tried are wrong — the canonical example is the `flounpackproject.bat` wrapper, which builds a tempfile listing the project's component files and feeds that to `-F`. Don't call these CLIs without copying the wrapper's full incantation.

**Reproduction.** See [`sim-proj/dev-docs/flotherm/experiments/2026-04-27-overlay/`](https://github.com/svd-ai-lab/sim-proj/tree/main/dev-docs/flotherm/experiments/2026-04-27-overlay) — `RESULT.md` plus the captured `step3.log` and tree diffs.

### Next experiments (in order of cheapness)

1. **GUI headless bootstrap.** Launch Flotherm with the imported (FloXML-derived) project briefly, let the GUI create a fresh `BaseSolution/` matching the new geometry, then kill the GUI and call translator. The scaffolding now matches — translator should translate without crash. Requires UIA, but we have that wired already.
2. **Round-trip via Flotherm's own FloXML export** (if such a command exists). Schemas grep already shows `export_compact_model_floxml` but no project-level `export_floxml`. Confirming whether a menu action exists is a recording-oracle task — deferred until a human is available.

---

## Narrowed but still open: `<load_from_library>` returns `E/15001`

**Hypothesis under test.** The XSD declares `<library_name>` as a recursive `<library>` chain (`libraryIDNode`):

```xml
<xs:complexType name="libraryIDNode">
  <xs:choice minOccurs="0" maxOccurs="1">
    <xs:element name="library" type="libraryIDNode" />
  </xs:choice>
  <xs:attribute name="name" use="required"/>
  <xs:attribute name="count" type="xs:int"/>
</xs:complexType>
```

Maybe the failures come from one of the **9 syntactic axes**:

1. filesystem names throughout (`FloTHERM_Libraries → … → Aluminum__Pure_`)
2. filesystem ancestors, **display** name leaf (`… → Aluminum (Pure)`)
3. display names throughout (`FloTHERM Libraries → … → Aluminum (Pure)`)
4. leaf-only, filesystem name (`<library name="Aluminum__Pure_"/>`)
5. leaf-only, display name (`<library name="Aluminum (Pure)"/>`)
6. prepend `Libraries/` top
7. add `count="1"` at every level
8. skip the `FloTHERM_Libraries` root
9. display leaf, filesystem ancestors

**Result.** All 9 fail identically:

```
ERROR   E/15001 - Command failed to find library node
WARN    W/15000 - Aborting XML due to previous error
```

**What this proves.** None of the syntactic axes we vary make any difference. The failure cause is **environmental, not syntactic**.

### Three remaining hypotheses (descending likelihood)

1. **Missing precondition.** The library system might be loaded **lazily** by the GUI on first browse; without a prior `<refresh_library>` or `<import_library>`, the runtime has no library tree to look up against. Or a geometry must be **selected** (`<select_geometry>`), not just **named**, before resolution. Or some implicit GUI state (Materials tab open, library browser visible).
2. **Record-only command.** Like the broken `flotherm.bat -f` (ISSUE-003), the schema accepts it but the playback path doesn't actually wire it up. Several record-only commands sit in the catalogue (`pause_record_script`, `resume_record_script`, `solve_idle_event`).
3. **UUID addressing.** Some `library.catalog` entries use a 6-tuple integer suffix (`0,2,0,0,0,0`); that may be the canonical node ID, with `name` being a display label that the playback path doesn't translate back.

### How to discriminate (deferred — needs a human at the GUI)

```
1. Flotherm GUI:  Macro → Record FloSCRIPT → choose a fresh script name
2. Drag-drop Aluminum (Pure) from Library browser onto a cuboid
3. Macro → Stop FloSCRIPT
4. Open the recorded .xml — that is the canonical <load_from_library> form
```

The recording oracle settles it in one shot. Until then, **build attribute-by-hand** with `<create_attribute>` + `<modify_attribute>` for materials and sources. Don't suggest any of forms 1-9 in your FloSCRIPT — they're all wrong.

A cheaper autonomous probe to try first: prepend `<refresh_library/>` (or `<import_library>` — schema lookup needed) to one of the failing scripts. If it passes, hypothesis #1 is the answer.

**Reproduction.** See [`sim-proj/dev-docs/flotherm/experiments/2026-04-27-library-paths/`](https://github.com/svd-ai-lab/sim-proj/tree/main/dev-docs/flotherm/experiments/2026-04-27-library-paths) — `RESULT.md` plus the 7 standalone probe scripts.

---

## Quick-reference: what to do *today*

| Task | Path |
|---|---|
| Re-solve an existing project headlessly | Direct `translator.exe -p <ws> -n1` + `solexe.exe -p <ws>`, after `flotherm.bat -env`. **Works.** See `SKILL.md` "Direct batch" section. |
| Create a new project from scratch | GUI automation (Macro → Play FloSCRIPT). Headless-bootstrap is still blocked; the next experiment is GUI bootstrap + headless re-translate. |
| Author materials / sources | `<create_attribute>` + `<modify_attribute>`. Don't try `<load_from_library>` — see ISSUE-006. |
| Chain N FloSCRIPTs after one GUI click | `<project_run_script file_name="…"/>` — **verified on 2504** (2026-04-27). See `floscript_modeling.md` "Script chaining" for the orchestrator pattern and the three-probe verification. |
