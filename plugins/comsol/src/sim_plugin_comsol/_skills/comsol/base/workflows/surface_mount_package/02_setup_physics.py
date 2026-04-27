"""Set up Heat Transfer in Solids physics with all boundary conditions.

Physics features:
  - Heat source: Q = 4.44e7 W/m^3 on silicon chip (~20 mW total)
    Chip volume = 3 x 1.5 x 0.1 mm = 4.5e-10 m^3; P = Q*V = 20 mW
  - Convective heat flux: h = 50 W/(m^2*K), T_amb = 30 degC on exterior
  - Fixed temperature: T = 50 degC on voltage regulator boundary
  - Thin Layer 1: ground plate (copper, 0.1 mm thick)
  - Thin Layer 2: interconnect trace (copper, 5 um thick)
"""
import jpype

JI = jpype.JArray(jpype.JInt)

comp = model.component("comp1")

# --- Heat Transfer in Solids ---------------------------------------------
ht = comp.physics().create("ht", "HeatTransfer", "geom1")

# --- Heat source on the silicon chip (domain) ----------------------------
hs1 = ht.create("hs1", "HeatSource", 3)
hs1.selection().named("sel_chip")  # Ball selection created in materials step
hs1.set("Q0", "4.44e7[W/m^3]")
hs1.label("Chip Heat Source")

# --- Convective heat flux on all exterior boundaries ---------------------
hf1 = ht.create("hf1", "HeatFluxBoundary", 2)
hf1.selection().all()
hf1.set("HeatFluxType", "ConvectiveHeatFlux")
hf1.set("h", "50[W/(m^2*K)]")
hf1.set("Text", "303.15[K]")  # 30 degC
hf1.label("Forced Convection")

# --- Fixed temperature on voltage regulator boundary ---------------------
temp1 = ht.create("temp1", "TemperatureBoundary", 2)
temp1.selection().named("sel_vr")  # Ball selection at board end face x=-10
temp1.set("T0", "323.15[K]")  # 50 degC
temp1.label("Voltage Regulator")

# --- Thin Layer 1: ground plate (copper, 0.1 mm) ------------------------
tl1 = ht.create("tl1", "ThinLayer", 2)
tl1.selection().named("sel_gp")  # Ball selection at z=-0.9
tl1.set("ds", "1e-4[m]")  # 0.1 mm thickness
tl1.set("LayerType", "Conductive")
tl1.label("Ground Plate (Cu)")

# --- Thin Layer 2: interconnect trace (copper, 5 um) --------------------
tl2 = ht.create("tl2", "ThinLayer", 2)
tl2.selection().named("sel_ic")  # Ball selection at z=-0.1
tl2.set("ds", "5e-6[m]")  # 5 um thickness
tl2.set("LayerType", "Conductive")
tl2.label("Interconnect (Cu)")

# --- Verification --------------------------------------------------------
for tag in list(ht.feature().tags()):
    feat = ht.feature(tag)
    try:
        n = len(list(feat.selection().entities(jpype.JInt(2))))
        print(f"{feat.label()} ({tag}): {n} boundaries")
    except Exception:
        try:
            n = len(list(feat.selection().entities(jpype.JInt(3))))
            print(f"{feat.label()} ({tag}): {n} domains")
        except Exception:
            print(f"{feat.label()} ({tag}): default selection")

_result = {
    "step": "physics",
    "physics": "Heat Transfer in Solids",
    "features": [
        "Heat source Q=4.44e7 W/m^3 on chip (~20 mW)",
        "Convection h=50 W/(m^2*K), T_amb=30 degC",
        "Fixed T=50 degC (voltage regulator)",
        "Thin layer: ground plate 0.1 mm Cu",
        "Thin layer: interconnect 5 um Cu",
    ],
    "status": "ok",
}
