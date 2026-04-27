"""Snippet 01 — smoke test.

Verifies the Mechanical gRPC channel is alive and the IronPython
interpreter is responsive. Returns counts from the top-level model
scene. Intentionally does NOT touch `Project.Name` or
`Project.ProjectDirectory` because on Chinese-locale Windows those
return CJK bytes that break the gRPC response encoding
(see known_issues.md #1).

Runs inside Mechanical's IronPython — do NOT `import ansys.mechanical`.
The last bare expression is what comes back over gRPC.
"""
import json

json.dumps({
    "ok": True,
    "has_ExtAPI": ExtAPI is not None,                # noqa: F821
    "has_DataModel": DataModel is not None,          # noqa: F821
    "has_Model": Model is not None,                  # noqa: F821
    "n_analyses": len(Model.Analyses),               # noqa: F821
    "analysis_types": [str(a.AnalysisType) for a in Model.Analyses],  # noqa: F821
    "n_bodies": len(list(
        Model.Geometry.GetChildren(DataModelObjectCategory.Body, True)  # noqa: F821
    )),
    "mesh_nodes": Model.Mesh.Nodes,                  # noqa: F821
    "mesh_elements": Model.Mesh.Elements,            # noqa: F821
})
