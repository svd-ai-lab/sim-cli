# Workbench System Templates

Workbench template availability is a live product/configuration fact. Do not
copy a static inventory into task logic, and do not assume that a template shown
in an official example is visible on the user's machine.

## Required Discovery

Before calling `GetTemplate(...)`, query the running Workbench session:

```bash
uv run sim inspect workbench.templates.visible
uv run sim inspect "workbench.templates.resolve:<workflow intent>"
```

The resolver is intentionally generic. It reads `GetAllVisibleTemplates()`,
then probes common Workbench forms such as a plain template name, an `(ANSYS)`
suffix, and a solver-qualified call. Use its structured `attempts`, `errors`,
and `visible_templates` fields as evidence.

## When Resolution Fails

1. Treat `Template ... not found in Project` as a template/product availability
   condition, not a Workbench launch failure.
2. Compare the live `visible_templates` list with the task intent. Choose a
   workflow that is actually available, or report the missing product/template
   clearly.
3. Search official PyWorkbench docs/examples for the workflow shape, then use
   the resolver to translate the documented form to the live installation.
   Good starting points:
   - https://workbench.docs.pyansys.com/version/stable/user-guide.html
   - https://examples.workbench.docs.pyansys.com/version/stable/examples/
4. If the docs use `GetTemplate(TemplateName="X", Solver="Y")` or
   `GetTemplate(TemplateName="X (Y)")`, do not hardcode either form. Add or
   improve resolver candidates only when they are generic across workflows.

## Create Pattern

Use the resolved template, not a guessed name:

```python
probe = sim.inspect("workbench.templates.resolve:Static Structural")
template = probe["template"]
if template["solver"] is None:
    wb_template = GetTemplate(TemplateName=template["name"])
else:
    wb_template = GetTemplate(TemplateName=template["name"], Solver=template["solver"])
system = wb_template.CreateSystem()
```

For official examples, treat names such as `Static Structural (ANSYS)`,
`FLUENT`, or `Fluid Flow` as examples of what might resolve, not as a portable
template catalogue.
