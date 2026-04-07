# Step 8a (EX-01): Extract outlet area-weighted average temperature.
# Acceptance: value is extractable as a numeric (no specific range for EX-01).
#
# PyFluent 0.37.x: rep.compute() returns [{"report_name": [value, ...]}]

def _scalar_from_compute(result, key):
    """Extract first numeric value from PyFluent 0.37.x compute() result.
    Result format: [{"key": [value, ...]}]  or  {"key": [value, ...]}
    """
    try:
        entry = result[0] if isinstance(result, list) else result
        val = entry[key]
        return float(val[0]) if isinstance(val, (list, tuple)) else float(val)
    except Exception as e:
        print(f"extraction error for '{key}': {e}")
        return None

rep = solver.settings.solution.report_definitions
rep.surface["outlet-temp-avg"] = {}
outlet_rep = rep.surface["outlet-temp-avg"]
outlet_rep.report_type = "surface-areaavg"
outlet_rep.field = "temperature"
outlet_rep.surface_names = ["outlet"]

result = rep.compute(report_defs=["outlet-temp-avg"])
print(f"compute raw result: {result}")

temp_K = _scalar_from_compute(result, "outlet-temp-avg")
temp_C = round(temp_K - 273.15, 4) if temp_K is not None else None
print(f"outlet area-weighted avg temperature: {temp_K} K  /  {temp_C} °C")

_result = {
    "step": "extract-outlet-temp",
    "outlet_avg_temp_K": temp_K,
    "outlet_avg_temp_C": temp_C,
    "ok": temp_K is not None,
}
