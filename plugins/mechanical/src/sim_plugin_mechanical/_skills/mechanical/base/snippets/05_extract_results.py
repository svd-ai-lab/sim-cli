"""Snippet 05 — add deformation + stress results and extract max values.

Assumes the analysis has already been solved (run snippet 04 first
or open a .mechdb that has solve state).
"""
import json

result = {}
try:
    sol = Model.Analyses[0].Solution  # noqa: F821

    td = sol.AddTotalDeformation()
    eqv = sol.AddEquivalentStress()

    sol.EvaluateAllResults()

    result["ok"] = True
    result["total_deformation_m_max"] = td.Maximum.Value
    result["equivalent_stress_Pa_max"] = eqv.Maximum.Value
    result["children"] = [str(c.Name) for c in sol.Children]
except Exception as e:
    result["ok"] = False
    result["error"] = str(e)

json.dumps(result)
