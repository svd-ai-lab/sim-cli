"""Snippet 02 — enumerate the model scene.

Lists analyses, bodies, named selections, and mesh counts. Returns
only ASCII-safe fields (no project name / no project directory).
If you need the project directory, use the `list_files()` method on
the PyMechanical client from the host side instead.
"""
import json


def _safe_name(obj):
    """Encode any .NET/unicode string to ASCII with '?' for non-ASCII."""
    try:
        s = str(obj.Name)
    except Exception:
        return "<unnamed>"
    return "".join(c if ord(c) < 128 else "?" for c in s)


analyses_info = []
for a in Model.Analyses:  # noqa: F821
    analyses_info.append({
        "name": _safe_name(a),
        "type": str(a.AnalysisType),
        "n_children": len(a.Children),
    })

bodies = list(Model.Geometry.GetChildren(DataModelObjectCategory.Body, True))  # noqa: F821
ns_parent = Model.NamedSelections  # noqa: F821

json.dumps({
    "ok": True,
    "model_children_count": len(Model.Children),        # noqa: F821
    "n_analyses": len(Model.Analyses),                   # noqa: F821
    "analyses": analyses_info,
    "n_bodies": len(bodies),
    "bodies": [_safe_name(b) for b in bodies],
    "n_named_selections": (
        len(ns_parent.Children) if ns_parent is not None else 0
    ),
    "mesh_nodes": Model.Mesh.Nodes,                      # noqa: F821
    "mesh_elements": Model.Mesh.Elements,                # noqa: F821
})
