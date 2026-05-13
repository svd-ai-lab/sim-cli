# Input classification

Every sim-cli task starts with the same question: **which inputs must
the user supply, which may I default, and which can I derive from the
files in front of me?** The answer is the same three-bucket rule across
every driver.

---

## Category A — Physical decision inputs

**Must ask the user if absent. Non-negotiable.**

These define *what the simulation physically represents*:

- Geometry parameters (dimensions, feature sizes, orientations)
- Materials and material properties
- Boundary conditions (inlet velocities, heat loads, wall temperatures, …)
- Initial conditions
- Physics model choices (laminar vs turbulent, steady vs transient, …)
- **Acceptance criterion** — the outcome-based check that decides
  whether the task is complete (see [`acceptance.md`](acceptance.md))

User pressure to "just use defaults" does **not** override this. Phrases
like "just run it" / "跑完就好" / "use whatever makes sense" describe an
operation, not an outcome — treat them as a missing Category A input and
ask.

Values lifted from a reference example (`sdk/*/examples/`, workflow
READMEs, tutorial scripts) are **not defaults** — they describe a
specific published test case. You may offer them explicitly ("the
mixing_elbow example uses 0.4 m/s inlet — would you like to use those
values?") but you must wait for the user's confirmation before
adopting them.

---

## Category B — Operational inputs

**May default. Must disclose.**

These affect runtime / performance / convenience only, not what the
simulation physically represents:

- `--processors N` (parallelism)
- `--ui-mode gui | no_gui`
- `--mode meshing | solver` when only one makes sense for the task
- `--workspace PATH` (run directory / artifact location)
- `--driver-option KEY=VALUE` when the driver skill classifies the key
  as operational rather than physical
- Smoke-test iteration counts (e.g. "run 10 iters to check setup")
- Output verbosity, log locations

Defaults are fine, but surface them. A line like "Using 4 processors
and headless UI — reply if you want different" is enough.

---

## Category C — File-derivable inputs

**Infer from the actual files. Confirm if critical.**

These are facts about the user's input files that the solver itself can
tell you if you ask:

- Mesh cell count, face zones, cell zones
- Variables / fields present in a `.cas` / `.dat` / `.vtu`
- Boundary names and types from a mesh file
- Material IDs from an `.inp` deck
- Element types, node counts

**Rule**: derive these via a diagnostic snippet (`sim exec` with a tiny
`dir()` / inspect call), **not** from a reference example of a similar
case. A reference example describes its own files, not the user's.

For anything downstream decisions depend on (e.g. naming a boundary as
`inlet_cold` vs `inlet_hot`), confirm with the user before proceeding.

---

## Worked example

> User: "Here's my mesh file `flipchip.msh`. Run a steady thermal
> analysis."

Classification:

| Field | Category | Action |
|---|---|---|
| Ambient temperature | A | **Ask** — physical decision |
| Chip heat load | A | **Ask** — physical decision |
| Solver mode (steady) | A | User stated it |
| Acceptance criterion | A | **Ask** — "what outcome would make this run successful? e.g. max junction temp < 85 °C" |
| Number of processors | B | Default to 4, disclose |
| UI mode | B | Default to headless, disclose |
| Cell count, boundary names | C | Inspect via a diagnostic `sim exec` snippet |
| Material properties | A | **Ask** — did not come with the mesh |

Do not start the analysis until every Category A field has an explicit
value from the user.
