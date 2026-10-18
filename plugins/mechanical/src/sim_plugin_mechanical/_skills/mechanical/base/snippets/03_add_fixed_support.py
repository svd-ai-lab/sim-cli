"""Snippet 03 — add a fixed support to the first named selection.

Creates a Fixed Support on the first NamedSelection in the model.
If no named selection exists, returns an error in the result.

Precondition: geometry loaded, at least one NamedSelection defined
(usually from the CAD via SpaceClaim face tagging).
"""
import json

result = {}
try:
    analyses = Model.Analyses  # noqa: F821
    if len(analyses) == 0:
        raise Exception("no Analyses in Model — open a .mechdb first")

    static = analyses[0]

    ns_parent = Model.NamedSelections  # noqa: F821
    if ns_parent is None or len(ns_parent.Children) == 0:
        raise Exception("no NamedSelections available — CAD needs face tags")

    ns = ns_parent.Children[0]

    fs = static.AddFixedSupport()
    fs.Location = ns

    result["ok"] = True
    result["bc_name"] = str(fs.Name)
    result["scoped_to"] = str(ns.Name)
    result["location_set"] = fs.Location is not None
except Exception as e:
    result["ok"] = False
    result["error"] = str(e)

json.dumps(result)
