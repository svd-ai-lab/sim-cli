# Skills Layering — Design Plan (v2)

> Status: **proposal, awaiting review**
>
> This doc replaces the v1 draft. Key corrections from v1, all from
> review feedback:
>
> 1. There is **one** `SKILL.md` per driver (at the driver root), and it
>    is purely an index — not concatenated from per-layer fragments.
> 2. **No `sim skills` CLI subcommands.** The LLM already has Read /
>    Glob / Grep; wrapping them adds nothing.
> 3. **No `sim/skills.py` module.** v1 introduced one; it turned out to
>    be ~140 LOC of machinery for a contract that fits in ~40 LOC inside
>    `compat.py`. The v1 module and its tests have been deleted.

---

## 1. Problem (one paragraph)

Each driver currently ships a flat `sim-skills/<driver>/` tree. As we
add more SDK and solver versions, the API-specific bits (one SDK
release vs the next) and solver-specific bits (one solver release vs
the next) start fighting the cross-cutting bits (concepts, file
formats, license tips). We need a way to say "this reference is
generic; this snippet is SDK-rev-only; this known-issue is
solver-rev-only" *without* duplicating the whole tree per profile.

## 2. Layout

```
sim-skills/<driver>/
    SKILL.md            ← single entry point. Hand-written index that
                          tells the LLM where to look. Does NOT contain
                          actual knowledge — only pointers like
                          "for SDK API see sdk/<your-version>/, for
                          solver-specific quirks see solver/<ver>/".
    base/               ← knowledge that applies to ALL profiles. May
                          have arbitrary internal structure:
        concepts/
        reference/
        snippets/
        workflows/
    sdk/
        <sdk-rev-a>/
        <sdk-rev-b>/
    solver/
        <solver-rev-a>/
        <solver-rev-b>/
```

`base/` is always relevant. `sdk/<slug>/` and `solver/<slug>/` carry
deltas that apply only to specific profiles.

The same template applies to every driver. SDK-less drivers (e.g. those
that drive a solver purely through its scripting interface or a CLI
batch mode) just have an empty or absent `sdk/` directory.

## 3. compat.yaml change

Each profile gains two optional string fields:

```yaml
profiles:
  - name: <profile-name>
    sdk: ">=X.Y,<Z.W"
    solver_versions: ["<solver-rev-a>", "<solver-rev-b>"]
    runner_module: sim._runners.<driver>.<runner>
    active_sdk_layer: <sdk-slug>            # ← new
    active_solver_layer: "<solver-slug>"    # ← new
```

`base/` is implicit and always active — no field for it.

`active_sdk_layer` resolves to `sim-skills/<driver>/sdk/<value>/`.
`active_solver_layer` resolves to `sim-skills/<driver>/solver/<value>/`.

Either field may be omitted (e.g. SDK-less drivers leave
`active_sdk_layer` unset, drivers with no version-sensitive solver
content leave `active_solver_layer` unset). The current
`skill_revision` field is **deleted**.

## 4. Runtime contract

The only runtime requirement: when an LLM connects, it needs to know
which sdk/solver layers are active for its profile. Otherwise it can't
tell which `sdk/<slug>/` directory to read.

Wire it through the existing `/connect` response. After a successful
connect, sim-server returns:

```json
{
  "ok": true,
  "data": {
    "session_id": "...",
    "profile": "<profile-name>",
    "skills": {
      "root": "/path/to/sim-skills/<driver>",
      "index": "/path/to/sim-skills/<driver>/SKILL.md",
      "active_sdk_layer": "sdk/<sdk-slug>",
      "active_solver_layer": "solver/<solver-slug>"
    },
    ...
  }
}
```

The LLM reads `index` once, follows the pointers it finds there,
filtered by the active layers. sim-cli does no file reading, no
composition, no overlay logic. Path strings are the entire API.

## 5. Code changes

### `src/sim/compat.py`

- Add `Profile.active_sdk_layer: str | None = None`
- Add `Profile.active_solver_layer: str | None = None`
- Loader recognizes the two new keys; unrecognized keys still go into
  `Profile.extra` as today
- Delete `skill_revision` field from `Profile` (and from every
  `compatibility.yaml` — see §6)
- New helper:

  ```python
  def verify_skills_layout(skills_root: Path) -> list[str]:
      """For every profile in every driver compat.yaml, verify the
      declared sdk/solver layer directories exist on disk under
      <skills_root>/<driver>/. Returns a list of human-readable
      mismatch lines; empty list means healthy. Always checks that
      <skills_root>/<driver>/SKILL.md and <skills_root>/<driver>/base/
      exist."""
  ```

  ~30 lines, no module.

### `src/sim/server.py`

In `/connect`, after the runner is up and the profile is known, build
the `skills` dict and include it in the response. ~15 lines, including
locating `SIM_SKILLS_ROOT` (env var, fallback to sibling of sim-cli
checkout — same probe logic that lived in the deleted skills.py,
inlined as a 6-line function).

### `src/sim/cli.py`

No changes. The session client already JSON-passes the connect response
through; the LLM sees `skills` in its tool result automatically.

### Optional: `sim doctor`

If `sim doctor` already exists, hook `verify_skills_layout()` into it.
If it doesn't, skip — punt to a future PR. (Confirmed not to exist;
skipping.)

## 6. sim-skills migration

Per-driver, in dependency order. Each driver is a separate sim-skills PR.

1. **pybamm** — currently has only `SKILL.md`. Create `base/` with the
   existing content, write a fresh top-level `SKILL.md` index.
   Validates the loader/contract end-to-end on minimal content.
2. **openfoam** — SDK-less. Move existing `reference/`, `docs/`,
   `tests/` into `base/`. Create `solver/<rev>/` directories per
   supported release (initially empty `.gitkeep`). Hand-write SKILL.md
   index. compat.yaml profiles get `active_solver_layer`.
3. Drivers with both SDK and solver-version sensitivity — move bulk
   content into `base/`. Create one `sdk/<rev>/` per supported SDK
   release and triage which existing snippets/reference files are
   version-specific. Create `solver/<rev>/` directories (probably
   mostly empty at first). Hand-write SKILL.md index.
4. SDK-less drivers and drivers with smallest deltas — do last.

After each driver's PR lands, the corresponding `compatibility.yaml` in
sim-cli (or the plugin package, for out-of-tree drivers) is updated in
the same commit. The schema change in §3 must be additive and backward
compatible *for unmigrated drivers*: profiles without the two new
fields just get None for both, which means "no sdk/solver overlay,
base only".

## 7. SKILL.md content (template)

Each driver's top-level `SKILL.md` is hand-written. Suggested skeleton:

```markdown
# <driver> skill index

You are connected to <driver>. The sim-cli connect response told you
which active layers apply (`active_sdk_layer`, `active_solver_layer`).

## Always relevant — base/

- `base/concepts/` — what a case file is, what meshing means, …
- `base/reference/` — generic API and CLI reference
- `base/snippets/` — copy-pasteable starters
- `base/workflows/` — multi-step recipes

## SDK-version-specific — sdk/<your-active-sdk-layer>/

For example, if your active_sdk_layer is `<sdk-slug>`, look in
`sdk/<sdk-slug>/` for:
- the API surface (method names, kwargs)
- migration notes from earlier SDKs
- known SDK-version bugs

## Solver-version-specific — solver/<your-active-solver-layer>/

For example, if your active_solver_layer is `<solver-slug>`, look in
`solver/<solver-slug>/` for:
- features added/removed in this release
- license syntax quirks
- known issues

## Lookup order when answering a question

1. base/ for concepts and shape of the workflow
2. sdk/<active>/ for the exact API call
3. solver/<active>/ for any caveats

A file in sdk/ or solver/ overrides anything in base/ on the same
topic — if both exist, prefer the more specific one.
```

The override convention is **policy in the SKILL.md**, not enforced by
sim-cli. The LLM follows the index. This keeps the runtime stupid.

## 8. Tests

Tests live alongside `compat.py`. Create `tests/test_compat_skills.py`
(or fold into a new `tests/test_compat.py` — neither exists yet).

| # | Test | Asserts |
|---|------|---------|
| 1 | `profile_loads_active_layer_fields` | Synthetic compat.yaml with `active_sdk_layer` / `active_solver_layer` round-trips into `Profile` correctly. |
| 2 | `profile_active_layers_default_to_none` | A profile that omits both fields gets `None` / `None` and still loads. |
| 3 | `verify_skills_layout_passes_on_complete_tree` | Build a synthetic sim-skills tree with `<driver>/SKILL.md`, `<driver>/base/`, `<driver>/sdk/<sdk-slug>/`, `<driver>/solver/<solver-slug>/`. Pretend compat.yaml declares those active layers. `verify_skills_layout()` returns `[]`. |
| 4 | `verify_skills_layout_flags_missing_skill_md` | Drop `<driver>/SKILL.md` → mismatch entry. |
| 5 | `verify_skills_layout_flags_missing_base` | Drop `<driver>/base/` → mismatch entry. |
| 6 | `verify_skills_layout_flags_missing_sdk_layer` | compat.yaml declares an `active_sdk_layer` slug for which no directory exists → mismatch entry. |
| 7 | `verify_skills_layout_flags_missing_solver_layer` | symmetric. |
| 8 | `verify_skills_layout_skips_unset_layers` | A profile with `active_sdk_layer: None` doesn't trigger any sdk-related check. |
| 9 | `connect_response_includes_skills_block` | (server-side, async test) `/connect` against a fake driver returns a response whose `data.skills` block has `root`, `index`, `active_sdk_layer`, `active_solver_layer`. |
| 10 | `connect_response_skills_root_is_none_when_tree_absent` | If `SIM_SKILLS_ROOT` is unset and there's no sibling tree, `data.skills.root` is `None` and connect still succeeds. |

All tests use `tempfile` synthetic trees. No dependency on the real
sim-skills repo.

## 9. Order of execution (after this plan is approved)

1. Schema + loader change in `compat.py` (§5), with tests #1, #2 above.
2. `verify_skills_layout()` in `compat.py` with tests #3 – #8.
3. `/connect` server change in `server.py` with tests #9, #10.
4. Per-driver sim-skills migration PRs in the order from §6. Each PR
   updates that driver's `compatibility.yaml` to set the two active
   layer fields and removes `skill_revision`.
5. Once every driver is migrated, delete the back-compat tolerance for
   `skill_revision` (a one-line removal — until then the loader
   accepts and ignores it with a warning).

## 10. What this plan deliberately does NOT do

- No file composition / overlay logic in sim-cli. The runtime returns
  paths; the LLM does the rest.
- No `sim skills *` CLI subcommands.
- No `sim/skills.py` module. Everything fits in `compat.py` + a small
  block in `server.py`.
- No `SKILL.md` concatenation across layers. One driver, one index,
  hand-written.
- No automatic layer detection from `sdk:` / `solver_versions:` ranges.
  Authors set `active_sdk_layer` and `active_solver_layer` explicitly
  — explicit is reviewable, magic isn't.
- No templating in skill files.

## 11. Net effect

Code: `compat.py` grows by ~50 LOC. `server.py` grows by ~20 LOC. No
new modules. Total surface area is much smaller than v1's plan.

Content: each driver's sim-skills tree gains a top-level `SKILL.md`
plus three subdirectories. The bulk of existing content moves into
`base/` unchanged. New solver/SDK versions add a directory each, no
duplication.

LLM ergonomics: one connect call hands the agent a stable starting
path and the names of its active overlay layers. From there, the agent
works with the same Read/Glob/Grep tools it already has.

---

## 12. Open questions for review

1. **Layer slug convention.** Should the slug repeat the SDK package
   name (e.g. `sdk/<sdk-package>-<rev>/`) or stay terse (e.g.
   `sdk/<rev>/`, since the parent dir already names the driver)?
2. **`active_sdk_layer` value format.** Same question — does the yaml
   value include the SDK-package prefix, or just the rev?
3. **Should `verify_skills_layout()` be wired into a CI step now**, or
   only added as a function for later use? (I lean: add the function,
   no CI hook yet — wiring it into CI requires both repos to migrate
   in lockstep, which is the thing we're trying to avoid.)
4. **`skills.root` when sim-skills isn't installed.** Currently I plan
   to return `None`. Alternative: return the path it *would* be at
   (sibling of sim-cli) so the LLM can at least produce a useful error
   message. Preference?

Once these are settled I'll start with step 1 of §9 (TDD: write
`tests/test_compat.py` red, then make it green).
