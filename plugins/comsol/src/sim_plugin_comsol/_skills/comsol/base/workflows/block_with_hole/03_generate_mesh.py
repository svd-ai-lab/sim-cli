"""Generate mesh with fine resolution."""
mesh = model.component("comp1").mesh().create("mesh1")
mesh.autoMeshSize(4)  # 4 = fine
mesh.run()

_result = {"step": "mesh", "size": "fine", "status": "ok"}
