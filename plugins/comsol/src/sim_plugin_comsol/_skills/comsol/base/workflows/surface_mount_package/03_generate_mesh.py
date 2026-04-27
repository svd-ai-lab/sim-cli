"""Generate mesh with local refinement on key boundaries.

Global size: Fine (level 4).
Extra-fine refinement on the voltage regulator boundary and ground plate
to resolve the steep thermal gradients near these heat paths.
Expected: ~30k tetrahedral elements.
"""
import jpype

mesh = model.component("comp1").mesh().create("mesh1")

# Global size: Fine
mesh.autoMeshSize(jpype.JDouble(4))

# Local refinement on voltage regulator boundary
sz1 = mesh.create("size1", "Size")
sz1.selection().geom("geom1", jpype.JInt(2))
sz1.selection().named("sel_vr")  # Ball selection from materials step
sz1.set("hauto", jpype.JDouble(3))  # extra fine
sz1.label("Regulator Refinement")

# Local refinement on ground plate boundary
sz2 = mesh.create("size2", "Size")
sz2.selection().geom("geom1", jpype.JInt(2))
sz2.selection().named("sel_gp")  # Ball selection from materials step
sz2.set("hauto", jpype.JDouble(3))  # extra fine
sz2.label("Ground Plate Refinement")

# Free tetrahedral meshing
ftet = mesh.create("ftet1", "FreeTet")
ftet.label("Free Tetrahedral")

mesh.run()

# --- Verification --------------------------------------------------------
stat = mesh.stat()
nelem = stat.getNumElem()
qual = stat.getMinQuality()
print(f"Elements: {nelem}, min quality: {qual:.4f}")

_result = {
    "step": "mesh",
    "global_size": "fine",
    "elements": nelem,
    "min_quality": round(qual, 4),
    "status": "ok",
}
