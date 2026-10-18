"""Add Heat Transfer in Solids physics with boundary conditions."""
import jpype

ht = model.component("comp1").physics().create("ht", "HeatTransfer", "geom1")

# Hot side: fixed temperature 373K
temp1 = ht.create("temp1", "TemperatureBoundary", 2)
temp1.selection().set(jpype.JArray(jpype.JInt)([1]))
temp1.set("T0", "373[K]")

# Cold side: fixed temperature 293K
temp2 = ht.create("temp2", "TemperatureBoundary", 2)
temp2.selection().set(jpype.JArray(jpype.JInt)([6]))
temp2.set("T0", "293[K]")

# Hole surface: convective cooling
hf = ht.create("hf1", "HeatFluxBoundary", 2)
hf.selection().set(jpype.JArray(jpype.JInt)([7, 8, 9]))
hf.set("HeatFluxType", "ConvectiveHeatFlux")
hf.set("h", "50[W/(m^2*K)]")
hf.set("Text", "293[K]")

_result = {
    "step": "physics",
    "physics": "Heat Transfer in Solids",
    "BCs": ["left=373K", "right=293K", "hole=convection h=50 W/(m2*K)"],
    "status": "ok",
}
