# Step 4: Copy water-liquid from database and assign to fluid cell zone.
solver.settings.setup.materials.database.copy_by_name(type="fluid", name="water-liquid")

# Assign to the fluid cell zone (elbow-fluid for mixing_elbow example)
cell_zones = list(solver.settings.setup.cell_zone_conditions.fluid.keys())
if not cell_zones:
    raise RuntimeError("No fluid cell zones found after reading mesh")

cell_zone = cell_zones[0]
# PyFluent 0.37.x: .material is a direct attribute, not under .general
solver.settings.setup.cell_zone_conditions.fluid[cell_zone].material = "water-liquid"

_result = {
    "step": "setup-material",
    "material": "water-liquid",
    "cell_zone": cell_zone,
    "ok": True,
}
