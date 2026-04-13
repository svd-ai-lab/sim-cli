"""Script that imports pybamm but never calls solve."""
import pybamm

model = pybamm.lithium_ion.SPM()
sim = pybamm.Simulation(model)
# Forgot to call sim.solve()
