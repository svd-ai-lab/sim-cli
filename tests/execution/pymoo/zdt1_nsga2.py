"""pymoo E2E — ZDT1 with NSGA-II.

ZDT1 is a 30-var, 2-objective convex Pareto front benchmark.
Acceptance: NSGA-II with 40-pop / 50-gen produces >=20 Pareto solutions
with f1_min < 0.05 (Pareto front passes through f1=0).
"""
import json
from pymoo.algorithms.moo.nsga2 import NSGA2
from pymoo.problems import get_problem
from pymoo.optimize import minimize


def main():
    problem = get_problem("zdt1")
    algo = NSGA2(pop_size=40)
    res = minimize(problem, algo, ('n_gen', 50), seed=1, verbose=False)
    n = int(len(res.F))
    f1m = float(res.F[:, 0].min())
    f2m = float(res.F[:, 1].min())
    print(json.dumps({
        "ok": n >= 20 and f1m < 0.05,
        "n_pareto": n,
        "f1_min": f1m,
        "f2_min": f2m,
    }))


if __name__ == "__main__":
    main()
