"""Valid Gmsh Python script - sphere via gmsh API."""
import gmsh

gmsh.initialize()
gmsh.model.add("sphere")
gmsh.model.occ.addSphere(0, 0, 0, 1.0, 1)
gmsh.model.occ.synchronize()
gmsh.model.mesh.generate(3)
gmsh.write("sphere.msh")
gmsh.finalize()
