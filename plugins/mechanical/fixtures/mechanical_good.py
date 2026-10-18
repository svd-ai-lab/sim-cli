"""Minimal Mechanical script — uses ExtAPI markers."""
import json
result = {
    "ok": True,
    "n_analyses": len(Model.Analyses),
    "project": str(ExtAPI.DataModel.Project.ProjectDirectory),
}
json.dumps(result)
