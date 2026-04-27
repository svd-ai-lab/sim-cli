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
