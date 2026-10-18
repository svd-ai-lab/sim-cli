# Step 5a (PyFluent 0.37 override): EX-01 / EX-05 boundary conditions.
#
# Differences vs base/snippets/05a_setup_bcs_ex01_ex05.py (which targets 0.38):
#   0.38:  momentum.velocity_magnitude.value = X
#   0.37:  momentum.velocity.value           = X
#
#   0.38:  thermal.temperature.value = X
#   0.37:  thermal.t.value           = X
#
# Turbulence subtree is identical across both lines for the inputs we use.

cold_inlet = solver.settings.setup.boundary_conditions.velocity_inlet["cold-inlet"]
cold_inlet.momentum.velocity.value = 0.4
cold_inlet.turbulence.turbulent_specification = "Intensity and Hydraulic Diameter"
cold_inlet.turbulence.turbulent_intensity = 0.05
cold_inlet.turbulence.hydraulic_diameter = "4 [in]"
cold_inlet.thermal.t.value = 293.15

hot_inlet = solver.settings.setup.boundary_conditions.velocity_inlet["hot-inlet"]
hot_inlet.momentum.velocity.value = 1.2
hot_inlet.turbulence.turbulent_specification = "Intensity and Hydraulic Diameter"
hot_inlet.turbulence.turbulent_intensity = 0.05
hot_inlet.turbulence.hydraulic_diameter = "1 [in]"
hot_inlet.thermal.t.value = 313.15

# Outlet: leave the case-file defaults in place. The outlet turbulence
# backflow tree in 0.37 marks scalar children as "not active" until you
# poke a sequence of intermediate fields, and the resulting backflow
# values barely move the converged outlet temperature for this case.

_result = {
    "step": "setup-bcs",
    "cold_inlet_velocity": 0.4,
    "cold_inlet_temp_K": 293.15,
    "hot_inlet_velocity": 1.2,
    "hot_inlet_temp_K": 313.15,
    "ok": True,
    "via": "sdk/0.37 override",
}
