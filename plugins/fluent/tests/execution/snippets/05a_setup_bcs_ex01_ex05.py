# Step 5a: Set boundary conditions for EX-01 and EX-05.
# cold-inlet: 0.4 m/s / 20°C (293.15 K), hydraulic diameter 4 in, intensity 5%
# hot-inlet:  1.2 m/s / 40°C (313.15 K), hydraulic diameter 1 in, intensity 5%
# outlet:     pressure outlet, turbulent intensity 5%, viscosity ratio 4
#
# PyFluent 0.37.x API paths (differ from 0.38 reference docs):
#   .momentum.velocity.value          (not .velocity_magnitude.value)
#   .turbulence.turbulent_specification (not .turbulence_specification)
#   .thermal.t.value                  (not .thermal.temperature.value)

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

outlet = solver.settings.setup.boundary_conditions.pressure_outlet["outlet"]
# Must set specification before the viscosity ratio field becomes active.
# PyFluent 0.37.x: writable field is turbulent_viscosity_ratio_real (not turbulent_viscosity_ratio)
outlet.turbulence.turbulent_specification = "Intensity and Viscosity Ratio"
outlet.turbulence.turbulent_intensity = 0.05
outlet.turbulence.turbulent_viscosity_ratio_real = 4

_result = {
    "step": "setup-bcs",
    "cold_inlet_velocity": 0.4,
    "cold_inlet_temp_K": 293.15,
    "hot_inlet_velocity": 1.2,
    "hot_inlet_temp_K": 313.15,
    "ok": True,
}
