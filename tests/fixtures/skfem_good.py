"""Minimal scikit-fem Poisson solver."""
import json
from skfem import MeshTri, Basis, ElementTriP1, BilinearForm, LinearForm, asm, condense, solve
from skfem.helpers import dot, grad


@BilinearForm
def laplace(u, v, w):
    return dot(grad(u), grad(v))


@LinearForm
def rhs(v, w):
    return 1.0 * v


m = MeshTri().refined(3)
basis = Basis(m, ElementTriP1())
A = asm(laplace, basis)
b = asm(rhs, basis)
x = solve(*condense(A, b, D=basis.get_dofs()))
print(json.dumps({"ok": True, "u_max": float(x.max()), "nodes": m.nvertices}))
