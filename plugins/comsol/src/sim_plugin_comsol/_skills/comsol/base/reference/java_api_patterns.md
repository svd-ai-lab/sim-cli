# Java API probing patterns

This is not a COMSOL API reference. It is a small set of stable probing
patterns for discovering the live model shape before modifying it.

## Rules

- Ask for `tags()` before accessing a child by tag.
- Ask for `properties()` before calling `set(...)`.
- Ask for `getType()` and `name()` when a feature's behavior is unclear.
- Check selections before solving; empty selections are a common hidden
  failure.
- Wrap exploratory calls in `try/except`; older COMSOL versions may lack
  optional helpers.
- Keep probing snippets read-only and return data through `_result`.

## Generic helpers

```python
def safe_call(label, fn):
    try:
        return fn()
    except Exception as exc:
        return {"error": label, "type": type(exc).__name__, "message": str(exc)}

def tags(container):
    return safe_call("tags", lambda: list(container.tags()))

def props(node):
    return safe_call("properties", lambda: list(node.properties()))
```

## Explore the model tree

```python
out = {"components": tags(model.component())}

for comp_tag in out["components"]:
    if isinstance(comp_tag, dict):
        continue
    comp = model.component(comp_tag)
    out.setdefault("component", {})[comp_tag] = {
        "geom": tags(comp.geom()),
        "material": tags(comp.material()),
        "physics": tags(comp.physics()),
        "mesh": tags(comp.mesh()),
    }

out["studies"] = tags(model.study())
out["results"] = tags(model.result())
_result = out
```

## Inspect one physics feature

```python
comp = model.component("comp1")
phys = comp.physics("ht")
feat = phys.feature("temp1")

selection = safe_call("selection", lambda: list(feat.selection().entities()))

_result = {
    "physics_tag": "ht",
    "feature_tag": "temp1",
    "type": safe_call("getType", lambda: feat.getType()),
    "name": safe_call("name", lambda: feat.name()),
    "properties": props(feat),
    "selection_entities": selection,
}
```

## Inspect a material

```python
mat = model.component("comp1").material("mat1")
_result = {
    "tag": "mat1",
    "type": safe_call("getType", lambda: mat.getType()),
    "name": safe_call("name", lambda: mat.name()),
    "properties": props(mat),
    "property_groups": tags(mat.propertyGroup()),
    "selection_entities": safe_call("selection", lambda: list(mat.selection().entities())),
}
```

## Inspect selections

Selections are often the difference between a model that looks plausible
and one that solves the wrong problem.

```python
comp = model.component("comp1")
out = {"component": "comp1", "selections": tags(comp.selection())}

for sel_tag in out["selections"]:
    if isinstance(sel_tag, dict):
        continue
    sel = comp.selection(sel_tag)
    out.setdefault("details", {})[sel_tag] = {
        "type": safe_call("getType", lambda: sel.getType()),
        "entities": safe_call("entities", lambda: list(sel.entities())),
    }

_result = out
```

## Before setting a property

Use this pattern before writing to an unfamiliar feature:

```python
feat = model.component("comp1").physics("ht").feature("hf1")
available = set(feat.properties())

if "q0" not in available:
    _result = {
        "ok": False,
        "reason": "property_not_available",
        "available_properties": sorted(available),
    }
else:
    feat.set("q0", "10[W/m^2]")
    _result = {"ok": True, "changed": "ht.hf1.q0"}
```

Do not record the resulting property list as a global truth. It is only
confirmed for this COMSOL version, module set, physics interface, and
feature type.
