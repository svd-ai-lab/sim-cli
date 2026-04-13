"""Script that uses pybamm without importing it."""
model = pybamm.lithium_ion.SPM()
sim = pybamm.Simulation(model)
sol = sim.solve([0, 3600])
