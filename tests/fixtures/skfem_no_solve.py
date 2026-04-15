"""scikit-fem script without calling solve — warning, not error."""
from skfem import MeshTri, Basis, ElementTriP1

m = MeshTri().refined(2)
basis = Basis(m, ElementTriP1())
print("mesh created, nothing solved")
