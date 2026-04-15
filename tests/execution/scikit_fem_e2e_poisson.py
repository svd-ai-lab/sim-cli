"""scikit-fem E2E: Poisson equation on unit square.

Solves -Δu = 1 on Ω = [0,1]×[0,1] with u=0 on ∂Ω.

Analytical solution has max ≈ 0.073671 at the center (0.5, 0.5).
FEM with P1 triangles on a refined mesh should match to ~1% accuracy.

Run via: sim run tests/execution/scikit_fem_e2e_poisson.py --solver scikit_fem
"""
import json
import sys
from skfem import MeshTri, Basis, ElementTriP1, BilinearForm, LinearForm, asm, condense, solve
from skfem.helpers import dot, grad


@BilinearForm
def laplace(u, v, w):
    return dot(grad(u), grad(v))


@LinearForm
def rhs(v, w):
    return 1.0 * v


def main():
    # Refined mesh for accuracy
    m = MeshTri().refined(4)
    basis = Basis(m, ElementTriP1())

    A = asm(laplace, basis)
    b = asm(rhs, basis)

    # Dirichlet u=0 on all boundary DOFs
    D = basis.get_dofs()
    x = solve(*condense(A, b, D=D))

    u_max = float(x.max())

    # Find location of maximum
    import numpy as np
    imax = int(np.argmax(x))
    xmax, ymax = float(m.p[0, imax]), float(m.p[1, imax])

    result = {
        "ok": True,
        "step": "poisson-unit-square",
        "nodes": int(m.nvertices),
        "elements": int(m.nelements),
        "u_max": u_max,
        "u_max_location": [xmax, ymax],
        "analytical_u_max": 0.073671,
        "relative_error": abs(u_max - 0.073671) / 0.073671,
        "solver": "scikit_fem",
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
