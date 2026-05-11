# Capability Discovery

Use this before implementing a Mechanical workflow that is not already covered
by a proven local snippet. The goal is to discover what the live Mechanical
session can do, then write a small setup step that fits that state.

## Query First

Run these against the live session:

```bash
uv run sim inspect mechanical.model.summary
uv run sim inspect mechanical.capabilities
uv run sim inspect mechanical.object.properties:geometry
uv run sim inspect mechanical.object.properties:mesh
```

For a specific analysis, use:

```bash
uv run sim inspect mechanical.capabilities:analysis:0
uv run sim inspect mechanical.object.properties:analysis:0
uv run sim inspect mechanical.object.properties:solution:0
```

Use the returned method lists to choose APIs such as `Model.Add...Analysis()`,
`analysis.Add...()`, and `solution.Add...()`. Do not guess from a model name,
tree label, or `AnalysisType` string alone.

## Confirm With Docs

When the live method list is unclear, search official PyMechanical scripting
docs and examples, then verify the documented method exists in
`mechanical.capabilities` before using it:

- https://mechanical.docs.pyansys.com/version/stable/examples/
- https://scripting.mechanical.docs.pyansys.com/version/stable/

If the docs and live session disagree, trust the live session for execution and
record the version/product mismatch in the result.

## Probe Before Full Setup

Before applying loads, solving, or extracting results, run one bounded
IronPython probe that returns structured facts:

```python
import json

analysis = Model.Analyses[0] if len(Model.Analyses) else None
data = {
    "ok": analysis is not None,
    "analysis_type": str(analysis.AnalysisType) if analysis else None,
    "analysis_add_methods": sorted([x for x in dir(analysis) if x.startswith("Add")]) if analysis else [],
    "solution_add_methods": sorted([x for x in dir(analysis.Solution) if x.startswith("Add")]) if analysis else [],
    "body_count": len(Model.Geometry.GetChildren(DataModelObjectCategory.Body, True)),
    "named_selection_count": len(Model.NamedSelections.Children),
}
json.dumps(data)
```

Only proceed when the required analysis, scoping targets, load/BC methods, mesh
state, and result methods are present.

## Acceptance Rules

For solves, transport success is not enough. Require:

- `Solution.Status` is a completed state, not `SolveRequired` or `NotSolved`.
- `mechanical.messages` has no blocking errors.
- Expected result objects evaluate to finite numeric values.
- The result range or invariant is physically meaningful for the specific
  user problem.

If post-processing reports that a result cannot be loaded, classify it as a
solve/result failure and inspect messages plus solver files before retrying.
