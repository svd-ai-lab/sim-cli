"""PyBaMM parameter sweep: compare capacity fade at different C-rates.

A battery engineer uses this to answer: "how much faster does my cell
degrade at 2C vs 0.5C?" — critical for sizing warranty guarantees.
"""
import json

import pybamm

model = pybamm.lithium_ion.SPM({"SEI": "ec reaction limited"})
params = pybamm.ParameterValues("Mohtat2020")
params.update({"SEI kinetic rate constant [m.s-1]": 1e-14})

c_rates = [0.5, 1.0, 2.0]
results = []

for c_rate in c_rates:
    params_copy = params.copy()
    params_copy.set_initial_state(1)

    experiment = pybamm.Experiment(
        [
            (
                f"Discharge at {c_rate}C until 3V",
                "Rest for 10 minutes",
                f"Charge at {c_rate}C until 4.2V",
                "Hold at 4.2V until C/50",
            )
        ]
        * 5
    )

    sim = pybamm.Simulation(model, experiment=experiment, parameter_values=params_copy)
    sol = sim.solve()

    sv = sol.summary_variables
    results.append({
        "c_rate": c_rate,
        "final_capacity_Ah": round(float(sv["Capacity [A.h]"][-1]), 4),
        "LLI_pct": round(float(sv["Loss of lithium inventory [%]"][-1]), 4),
    })

print(json.dumps({"sweep": "c_rate", "results": results}))
