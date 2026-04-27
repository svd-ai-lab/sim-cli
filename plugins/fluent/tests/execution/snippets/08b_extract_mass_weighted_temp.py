# Step 8b (EX-02): Extract outlet mass-weighted average temperature.
# Acceptance criterion: value must be in 22–38°C range.
#
# PyFluent 0.37.x: rep.compute() returns [{"report_name": [value, ...]}]

def _scalar_from_compute(result, key):
    try:
        entry = result[0] if isinstance(result, list) else result
        val = entry[key]
        return float(val[0]) if isinstance(val, (list, tuple)) else float(val)
    except Exception as e:
        print(f"extraction error for '{key}': {e}")
        return None

rep = solver.settings.solution.report_definitions
rep.surface["outlet-temp-mwavg"] = {}
outlet_rep = rep.surface["outlet-temp-mwavg"]
outlet_rep.report_type = "surface-massavg"
outlet_rep.field = "temperature"
outlet_rep.surface_names = ["outlet"]

result = rep.compute(report_defs=["outlet-temp-mwavg"])
print(f"compute raw result: {result}")

temp_K = _scalar_from_compute(result, "outlet-temp-mwavg")
temp_C = round(temp_K - 273.15, 4) if temp_K is not None else None
in_range = (22.0 <= temp_C <= 38.0) if temp_C is not None else None

print(f"outlet mass-weighted avg temperature: {temp_K} K  /  {temp_C} °C")
print(f"acceptance criterion (22–38°C): {'PASS' if in_range else 'FAIL' if in_range is not None else 'UNKNOWN'}")

_result = {
    "step": "extract-mass-weighted-temp",
    "outlet_mass_weighted_avg_temp_K": temp_K,
    "outlet_mass_weighted_avg_temp_C": temp_C,
    "acceptance_22_38_C": in_range,
    "ok": temp_K is not None,
}
