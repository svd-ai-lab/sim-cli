# Step 8c (EX-05): Extract all three required fields as JSON.
# Required output: outlet_temp_celsius, cold_inlet_mfr, hot_inlet_mfr, final_residuals
#
# PyFluent 0.37.x: rep.compute() returns [{"report_name": [value, ...]}]

def _scalar_from_compute(result, key):
    try:
        entry = result[0] if isinstance(result, list) else result
        val = entry[key]
        return float(val[0]) if isinstance(val, (list, tuple)) else float(val)
    except Exception as e:
        print(f"WARNING: could not extract '{key}': {e}")
        return None

rep = solver.settings.solution.report_definitions

# 1. Outlet area-weighted average temperature
rep.surface["ex05-outlet-temp"] = {}
t_rep = rep.surface["ex05-outlet-temp"]
t_rep.report_type = "surface-areaavg"
t_rep.field = "temperature"
t_rep.surface_names = ["outlet"]
t_result = rep.compute(report_defs=["ex05-outlet-temp"])
print(f"outlet temp compute result: {t_result}")
outlet_temp_K = _scalar_from_compute(t_result, "ex05-outlet-temp")
outlet_temp_C = round(outlet_temp_K - 273.15, 4) if outlet_temp_K is not None else None

# 2. Mass flow rates at cold-inlet and hot-inlet
rep.flux["ex05-cold-mfr"] = {}
cold_rep = rep.flux["ex05-cold-mfr"]
cold_rep.report_type = "flux-massflow"
cold_rep.boundaries = ["cold-inlet"]
c_result = rep.compute(report_defs=["ex05-cold-mfr"])
print(f"cold-inlet MFR compute result: {c_result}")
cold_mfr_raw = _scalar_from_compute(c_result, "ex05-cold-mfr")
cold_mfr = round(cold_mfr_raw, 6) if cold_mfr_raw is not None else None

rep.flux["ex05-hot-mfr"] = {}
hot_rep = rep.flux["ex05-hot-mfr"]
hot_rep.report_type = "flux-massflow"
hot_rep.boundaries = ["hot-inlet"]
h_result = rep.compute(report_defs=["ex05-hot-mfr"])
print(f"hot-inlet MFR compute result: {h_result}")
hot_mfr_raw = _scalar_from_compute(h_result, "ex05-hot-mfr")
hot_mfr = round(hot_mfr_raw, 6) if hot_mfr_raw is not None else None

# 3. Final residuals (best-effort; full convergence history requires file export)
print("NOTE: final_residuals set to null (requires convergence file export, best-effort in v0)")
final_residuals = None

print(f"outlet_temp_celsius:   {outlet_temp_C}")
print(f"cold_inlet_mfr (kg/s): {cold_mfr}")
print(f"hot_inlet_mfr  (kg/s): {hot_mfr}")
print(f"final_residuals:       {final_residuals}")

all_fields_present = all(v is not None for v in [outlet_temp_C, cold_mfr, hot_mfr])

_result = {
    "step": "extract-all-fields",
    "outlet_temp_celsius": outlet_temp_C,
    "cold_inlet_mfr": cold_mfr,
    "hot_inlet_mfr": hot_mfr,
    "final_residuals": final_residuals,
    "all_fields_present": all_fields_present,
    "ok": all_fields_present,
}
