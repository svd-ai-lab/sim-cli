# Diagnostic: list all boundary zone names in the loaded mesh.
# Run this BEFORE setting up BCs to confirm zone names.
bc = solver.settings.setup.boundary_conditions

velocity_inlets = list(bc.velocity_inlet.keys()) if hasattr(bc, "velocity_inlet") else []
pressure_outlets = list(bc.pressure_outlet.keys()) if hasattr(bc, "pressure_outlet") else []
walls = list(bc.wall.keys()) if hasattr(bc, "wall") else []

cell_zones = list(solver.settings.setup.cell_zone_conditions.fluid.keys())

print("=== velocity_inlet zones ===")
for z in velocity_inlets:
    print(f"  {z}")
print("=== pressure_outlet zones ===")
for z in pressure_outlets:
    print(f"  {z}")
print("=== wall zones ===")
for z in walls:
    print(f"  {z}")
print("=== fluid cell zones ===")
for z in cell_zones:
    print(f"  {z}")

_result = {
    "velocity_inlets": velocity_inlets,
    "pressure_outlets": pressure_outlets,
    "walls": walls,
    "cell_zones": cell_zones,
}
