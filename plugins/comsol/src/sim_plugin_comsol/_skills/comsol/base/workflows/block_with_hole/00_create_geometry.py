"""Create a 3D block with a cylindrical hole."""
import jpype

comp = model.component().create("comp1", True)
geom = model.component("comp1").geom().create("geom1", 3)

blk = geom.create("blk1", "Block")
blk.set("size", jpype.JArray(jpype.JDouble)([1.0, 0.5, 0.2]))

cyl = geom.create("cyl1", "Cylinder")
cyl.set("r", 0.08)
cyl.set("h", 0.3)
cyl.set("pos", jpype.JArray(jpype.JDouble)([0.5, 0.25, -0.05]))

diff = geom.create("dif1", "Difference")
diff.selection("input").set("blk1")
diff.selection("input2").set("cyl1")

geom.run()

_result = {"step": "geometry", "description": "block with cylindrical hole", "status": "ok"}
