"""PyMFEM E2E: Poisson -Δu = 1 on unit square, u=0 on boundary.

Analytical max u ≈ 0.073671. MFEM with P1 triangles on refined mesh
should match within 1% error.
"""
import json
import sys

import mfem.ser as mfem


def main():
    # Build mesh: 20x20 triangular unit-square mesh
    mesh = mfem.Mesh(20, 20, "TRIANGLE", True, 1.0, 1.0)
    dim = mesh.Dimension()

    # H1 space, linear elements
    fec = mfem.H1_FECollection(1, dim)
    fespace = mfem.FiniteElementSpace(mesh, fec)
    dofs = fespace.GetTrueVSize()

    # Boundary attrs for Dirichlet (all boundaries = essential)
    ess_tdof_list = mfem.intArray()
    ess_bdr = mfem.intArray([1] * mesh.bdr_attributes.Max())
    fespace.GetEssentialTrueDofs(ess_bdr, ess_tdof_list)

    # Linear form: f = 1
    b = mfem.LinearForm(fespace)
    one = mfem.ConstantCoefficient(1.0)
    b.AddDomainIntegrator(mfem.DomainLFIntegrator(one))
    b.Assemble()

    # Bilinear form: -Δ
    a = mfem.BilinearForm(fespace)
    a.AddDomainIntegrator(mfem.DiffusionIntegrator(one))
    a.Assemble()

    # Solution vector, initialize to 0 (Dirichlet value)
    x = mfem.GridFunction(fespace)
    x.Assign(0.0)

    # Reduce to linear system with essential BCs eliminated
    A = mfem.SparseMatrix()
    B = mfem.Vector()
    X = mfem.Vector()
    a.FormLinearSystem(ess_tdof_list, x, b, A, X, B)

    # Direct solve via UMFPack if available, else GSSmoother + CG
    try:
        solver = mfem.UMFPackSolver()
        solver.SetOperator(A)
        solver.Mult(B, X)
    except Exception:
        M = mfem.GSSmoother(A)
        mfem.PCG(A, M, B, X, 0, 2000, 1e-14, 0.0)

    a.RecoverFEMSolution(X, b, x)

    # Extract max value
    u_arr = x.GetDataArray()
    u_max = float(u_arr.max())

    result = {
        "ok": True,
        "step": "pymfem-poisson",
        "dofs": int(dofs),
        "elements": int(mesh.GetNE()),
        "vertices": int(mesh.GetNV()),
        "u_max": u_max,
        "analytical_u_max": 0.073671,
        "relative_error": abs(u_max - 0.073671) / 0.073671,
        "solver": "pymfem",
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
