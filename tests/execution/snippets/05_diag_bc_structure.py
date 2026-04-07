# Diagnostic: inspect actual BC attribute paths in PyFluent 0.37.x
# Run after read_case + setup_physics + setup_material

cold_inlet = solver.settings.setup.boundary_conditions.velocity_inlet["cold-inlet"]

print("=== cold_inlet.momentum attributes ===")
for attr in sorted(dir(cold_inlet.momentum)):
    if not attr.startswith("_"):
        print(f"  {attr}")

print("=== cold_inlet.turbulence attributes ===")
for attr in sorted(dir(cold_inlet.turbulence)):
    if not attr.startswith("_"):
        print(f"  {attr}")

print("=== cold_inlet.thermal attributes ===")
for attr in sorted(dir(cold_inlet.thermal)):
    if not attr.startswith("_"):
        print(f"  {attr}")

_result = {"step": "diag-bc-structure", "ok": True}
