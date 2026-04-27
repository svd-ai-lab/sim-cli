"""Snippet 06 — observation coupling check.

Queries state that sim's observation commands need to be consistent
with. The contract (see reference/observation_commands.md):
    • sim inspect session.summary is LOCAL — no round-trip
    • this snippet's exec IS the round-trip — its return value proves
      the gRPC channel is live
    • sim screenshot should show a GUI window that matches these counts

ASCII-only output — avoids project name / directory to survive CJK
Windows locales (known_issues.md #1).
"""
import json

result = {"ok": True}
try:
    result["n_analyses"] = len(Model.Analyses)  # noqa: F821
    result["n_bodies"] = len(list(
        Model.Geometry.GetChildren(DataModelObjectCategory.Body, True)  # noqa: F821
    ))
    result["mesh_nodes"] = Model.Mesh.Nodes  # noqa: F821
    result["mesh_elements"] = Model.Mesh.Elements  # noqa: F821
    if len(Model.Analyses) > 0:  # noqa: F821
        a = Model.Analyses[0]  # noqa: F821
        result["first_analysis_type"] = str(a.AnalysisType)
        result["first_analysis_n_children"] = len(a.Children)
        result["solution_status"] = str(a.Solution.Status)
except Exception as e:
    result["ok"] = False
    result["error"] = "".join(c if ord(c) < 128 else "?" for c in str(e))

json.dumps(result)
