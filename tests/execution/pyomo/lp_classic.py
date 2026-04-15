"""Pyomo E2E — classic textbook LP.

max  3*x + 5*y
s.t. x       <= 4
      2*y    <= 12
     3*x + 2*y <= 18
     x, y >= 0

Optimal: (x, y) = (2, 6), obj = 36.

Acceptance: solver returns (2, 6) within tol 1e-4 with HiGHS or GLPK.
"""
import json
import pyomo.environ as pyo


def main():
    m = pyo.ConcreteModel()
    m.x = pyo.Var(within=pyo.NonNegativeReals)
    m.y = pyo.Var(within=pyo.NonNegativeReals)
    m.obj = pyo.Objective(expr=3*m.x + 5*m.y, sense=pyo.maximize)
    m.c1 = pyo.Constraint(expr=m.x <= 4)
    m.c2 = pyo.Constraint(expr=2*m.y <= 12)
    m.c3 = pyo.Constraint(expr=3*m.x + 2*m.y <= 18)

    solver = None
    for name in ('appsi_highs', 'glpk', 'cbc', 'ipopt'):
        try:
            s = pyo.SolverFactory(name)
            if s.available(exception_flag=False):
                solver = s; break
        except Exception:
            pass

    if solver is None:
        print(json.dumps({"ok": False, "error": "no LP solver available"})); return

    solver.solve(m)
    x, y, obj = float(pyo.value(m.x)), float(pyo.value(m.y)), float(pyo.value(m.obj))
    print(json.dumps({
        "ok": abs(x-2.0) < 1e-4 and abs(y-6.0) < 1e-4 and abs(obj-36.0) < 1e-4,
        "x": x, "y": y, "obj": obj,
    }))


if __name__ == "__main__":
    main()
