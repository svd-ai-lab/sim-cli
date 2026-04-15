"""Minimal PyMFEM script — create mesh and H1 space."""
import json
import mfem.ser as mfem

mesh = mfem.Mesh(4, 4, "TRIANGLE", True, 1.0, 1.0)
fec = mfem.H1_FECollection(1, mesh.Dimension())
fespace = mfem.FiniteElementSpace(mesh, fec)

print(json.dumps({
    "ok": True,
    "vertices": mesh.GetNV(),
    "elements": mesh.GetNE(),
    "dofs": fespace.GetTrueVSize(),
}))
