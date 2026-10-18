"""Snippet 04 — run the solve on analyses[0] and report status.

Blocking. If BCs are missing or invalid, this will return a
pre-solve error instead of running a partial solve.
"""
import json

result = {}
try:
    static = Model.Analyses[0]  # noqa: F821

    # Pre-flight — collect any red messages from Mechanical
    msgs = ExtAPI.Application.Messages  # noqa: F821
    pre_errors = [str(m.DisplayString) for m in msgs if str(m.Severity) == "Error"]
    if pre_errors:
        raise Exception("pre-solve errors: " + "; ".join(pre_errors[:3]))

    static.Solve(True)   # blocking

    result["ok"] = True
    result["status"] = str(static.Solution.Status)
    result["result_file"] = str(static.ResultFileName)
except Exception as e:
    result["ok"] = False
    result["error"] = str(e)

json.dumps(result)
