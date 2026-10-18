# TUI vs Settings API Guidance

Use whichever gets the job done. Neither is always better.

## When to prefer the Settings API

- **Typed and discoverable** — autocomplete, `.child_names`, `.get_state()` for introspection
- **Boundary conditions** — `wall[name].thermal.thermal_condition = "Temperature"` is readable
- **Models on/off** — `models.energy.enabled = True`
- **Material properties** — structured assignment with units
- **Named expressions** — `named_expressions["Power"] = {"definition": "1 [W]"}`

## When to prefer TUI

- **Surface creation from cell zones** — `solver.tui.surface.zone_surface(name, zone)` is one call vs navigating the results.surfaces settings tree
- **Version-stable operations** — TUI commands rarely change between Fluent releases; settings API paths do
- **Complex zone selection** — TUI supports wildcard patterns and zone lists natively
- **Quick report extraction** — when you just need a number printed to stdout
- **Undocumented operations** — some Fluent features don't have settings API equivalents yet

## When neither Settings nor TUI is enough by itself

Some Fluent features are workflows rather than single settings: they create
lookup tables, import mechanism files, initialize hidden model state, or
depend on staged dialogs. For these, first read the Fluent User's Guide /
Theory Guide workflow and identify the required artifacts. Then choose the
least brittle automation surface for each documented step.

Practical rules:

- If a Settings object is present but inactive, check which documented
  prerequisite has not been completed before trying a lower-level call.
- For flamelet/PDF workflows, import CHEMKIN as the material name
  `"flamelet-mixture"` after enabling the partially premixed model. A
  generic material import can succeed while leaving flamelet table controls
  unusable.
- Fluent's CHEMKIN TUI import order is material name, mechanism file, then
  thermo file. Quote every argument and avoid paths with spaces.
- If a TUI command prompts for several values, capture a complete journal or
  prompt transcript once; do not guess a positional argument list from the
  generated Python wrapper.
- If a command says `read_*` or `write_*`, verify whether it creates data or
  only imports/exports data created elsewhere.
- For generated PDF tables, `case/data` is not the whole persistent state:
  write the table with `write_pdf_cmd(...)` and read it back between
  `read_case(...)` and `read_data(...)`.
- Avoid undocumented internal Scheme procedures as production automation.
  Use them only for read-only introspection or not at all.

## Anti-patterns to avoid

- **Don't use TUI for everything** — settings API is better for structured setup (BCs, materials, models) because it's introspectable and type-safe
- **Don't hardcode version branches** — if an API call fails, introspect the object (`dir()`, `.child_names`) rather than checking `pyfluent.__version__` and branching
- **Don't mix approaches mid-operation** — if you start setting BCs via settings API, finish all BCs that way rather than switching to TUI halfway through

## Examples from the flip-chip demo

| Operation | Approach used | Why |
|-----------|--------------|-----|
| Enable energy equation | Settings API | Clean: `models.energy.enabled = True` |
| Set wall BCs (T=300K) | Settings API | Structured, loop over wall names |
| Define named expression | Settings API | `named_expressions["Power"] = ...` |
| Set die heat source | Settings API | `die.sources.terms = {...}` |
| Create surface from cell zone | TUI | `fields.reduction` rejects cell zone names |
| Extract max temperature | Settings API | `report_definitions` + `fields.reduction` on created surface |
