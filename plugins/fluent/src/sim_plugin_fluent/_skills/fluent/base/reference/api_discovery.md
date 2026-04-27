# PyFluent API Discovery Patterns

When a PyFluent settings API call fails (usually `AttributeError` after a version change), use these introspection patterns to find the correct path instead of hardcoding version branches.

## Pattern 1: Find renamed attributes with `dir()`

```python
# Expected: die.source_terms  →  AttributeError
# Discover what's actually there:
obj = solver.settings.setup.cell_zone_conditions.solid["zone-name"]
attrs = [a for a in dir(obj) if not a.startswith("_")]
# Found: 'sources' instead of 'source_terms'
```

## Pattern 2: Navigate settings tree with `.child_names`

```python
# Drill into an unfamiliar object:
obj.child_names   # → ['enable', 'terms']
obj.get_state()   # → full state dict, shows current values
obj.print_state() # → human-readable state dump
```

## Pattern 3: Cell zone vs surface names

`fields.reduction` and `report_definitions.surface_names` only accept **surface names**, not cell zone names. If you get `ValueError: Invalid location input`, create a surface from the cell zone first:

```python
# TUI approach (stable across versions):
solver.tui.surface.zone_surface("my_surface", "cell-zone-name")

# Settings API approach (pyfluent 0.38+):
solver.settings.results.surfaces.zone_surface["my_surface"] = {
    "zone_name": "cell-zone-name"
}

# Then use the surface name in reduction/reports:
solver.fields.reduction.maximum(expression="Temperature", locations=["my_surface"])
```

## Pattern 4: Named expressions

Some case files reference named expressions that aren't yet defined. Check for warnings like `Setup contains invalid expression` after reading a case.

```python
# List existing named expressions:
ne = solver.settings.setup.named_expressions
print(list(ne.keys()))

# Define a missing one:
ne["Power"] = {"definition": "1 [W]"}
```

## Pattern 5: Report definitions for data extraction

When `fields.reduction` doesn't work for a location, use report definitions:

```python
rd = solver.settings.solution.report_definitions

rd.surface["my_report"] = {}
rd.surface["my_report"].report_type = "surface-areaavg"  # or surface-facetmax
rd.surface["my_report"].field = "temperature"
rd.surface["my_report"].surface_names = ["surface-name"]  # must be a surface, not cell zone

rd.compute(report_defs=["my_report"])
# Values printed to stdout
```

## Pattern 6: Allowed values from error messages

PyFluent often includes allowed values in error messages:

```
ValueError: 'surface_names' has no attribute '['bad-name']'.
The allowed values are: ['pcb_top', 'die_sides', ...]
```

Parse these to discover valid surface/zone names without a separate query.

## Pattern 7: Version detection

```python
import ansys.fluent.core as pyfluent
version = pyfluent.__version__  # e.g. "0.38.1"
major_minor = ".".join(version.split(".")[:2])  # "0.38"
```

Use this to log which version is active, not to branch code paths. If an API call fails, introspect the object rather than checking the version string.

## When to use TUI instead

If introspection reveals the settings API path is complex or unreliable for a specific operation, use TUI directly. Common cases where TUI is simpler:

- Creating surfaces from cell zones (`surface/zone-surface`)
- Complex zone selection patterns
- Operations that would require multiple settings API calls but one TUI command
