"""FiPy E2E — steady-state 1D Poisson with prescribed Dirichlet BCs.

Equation: -d/dx(D dphi/dx) = 0 on [0, 1], phi(0) = 1, phi(1) = 0.
Analytical: phi(x) = 1 - x. Mid value at x=0.5 -> 0.5.

Acceptance: |phi(0.5) - 0.5| < 0.01 with 50-cell grid.
"""
import json
from fipy import CellVariable, Grid1D, DiffusionTerm


def main():
    nx, dx, D = 50, 1.0 / 50, 1.0
    mesh = Grid1D(nx=nx, dx=dx)
    phi = CellVariable(name='phi', mesh=mesh, value=0.5)
    phi.constrain(1.0, mesh.facesLeft)
    phi.constrain(0.0, mesh.facesRight)

    eq = DiffusionTerm(coeff=D) == 0
    eq.solve(var=phi)

    mid_idx = nx // 2
    mid_val = float(phi.value[mid_idx])
    expected = 1.0 - (mid_idx + 0.5) * dx     # cell-center coord
    err = abs(mid_val - expected)
    print(json.dumps({
        "ok": err < 0.01,
        "mid_value": mid_val,
        "expected": expected,
        "abs_error": err,
        "n_cells": nx,
    }))


if __name__ == "__main__":
    main()
