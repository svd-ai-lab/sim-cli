"""Assign aluminum material to all domains."""
import jpype

mat = model.component("comp1").material().create("mat1", "Common")
mat.propertyGroup("def").set("thermalconductivity", jpype.JArray(jpype.JString)(["237[W/(m*K)]"]))
mat.propertyGroup("def").set("density", jpype.JArray(jpype.JString)(["2700[kg/m^3]"]))
mat.propertyGroup("def").set("heatcapacity", jpype.JArray(jpype.JString)(["900[J/(kg*K)]"]))
mat.label("Aluminum")
mat.selection().all()

_result = {"step": "material", "material": "Aluminum", "status": "ok"}
