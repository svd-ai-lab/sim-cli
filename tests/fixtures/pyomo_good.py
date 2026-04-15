"""Minimal Pyomo script."""
import json
import pyomo.environ as pyo
m = pyo.ConcreteModel()
m.x = pyo.Var(within=pyo.NonNegativeReals)
m.obj = pyo.Objective(expr=2*m.x, sense=pyo.minimize)
print(json.dumps({"ok": True, "n_vars": 1}))
