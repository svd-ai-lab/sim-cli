# Step 4 (PyFluent 0.37 override): water-liquid + assign to fluid cell zone.
#
# Difference vs base/snippets/04_setup_material.py:
#   0.38+:  cell_zone.fluid[name].general.material = "water-liquid"
#   0.37:   cell_zone.fluid[name].material         = "water-liquid"
#
# This is the only EX-01 step that needs a per-SDK override.
solver.settings.setup.materials.database.copy_by_name(type="fluid", name="water-liquid")

cell_zones = list(solver.settings.setup.cell_zone_conditions.fluid.keys())
if not cell_zones:
    raise RuntimeError("No fluid cell zones found after reading mesh")

cell_zone = cell_zones[0]
solver.settings.setup.cell_zone_conditions.fluid[cell_zone].material = "water-liquid"

_result = {
    "step": "setup-material",
    "material": "water-liquid",
    "cell_zone": cell_zone,
    "ok": True,
    "via": "sdk/0.37 override",
}
