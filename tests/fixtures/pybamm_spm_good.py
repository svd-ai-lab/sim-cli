"""Realistic PyBaMM simulation: cycle aging with SEI degradation.

Simulates 10 charge-discharge cycles of a lithium-sim cell with SEI growth,
tracking capacity fade and lithium inventory loss. This is the kind of
simulation a battery engineer would run to predict cell aging behavior.
"""
import json

import pybamm

# SPM with SEI degradation — the standard aging model
model = pybamm.lithium_ion.SPM({"SEI": "ec reaction limited"})

# Industry-standard NMC parameter set, tuned for visible degradation
params = pybamm.ParameterValues("Mohtat2020")
params.update({"SEI kinetic rate constant [m.s-1]": 1e-14})
params.set_initial_state(1)

# CCCV cycling protocol — what every cell test lab runs
experiment = pybamm.Experiment(
    [
        (
            "Discharge at 1C until 3V",
            "Rest for 10 minutes",
            "Charge at 1C until 4.2V",
            "Hold at 4.2V until C/50",
        )
    ]
    * 10
)

sim = pybamm.Simulation(model, experiment=experiment, parameter_values=params)
sol = sim.solve()

# Extract key metrics an engineer cares about
sv = sol.summary_variables
capacity_Ah = float(sv["Capacity [A.h]"][-1])
LLI_pct = float(sv["Loss of lithium inventory [%]"][-1])
cycles = int(sv["Cycle number"][-1])

print(json.dumps({
    "capacity_Ah": round(capacity_Ah, 4),
    "LLI_pct": round(LLI_pct, 4),
    "cycles": cycles,
    "model": "SPM",
    "degradation": "SEI",
}))
