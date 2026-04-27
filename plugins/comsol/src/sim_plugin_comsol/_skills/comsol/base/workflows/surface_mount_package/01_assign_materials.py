"""Assign five materials to the surface-mount package model.

Strategy: assign Aluminum to all domains first (pins are the majority),
then override with specific materials for board, package body, chip,
and copper for thin-layer boundaries.

Materials: Aluminum (pins), FR4 (board), Plastic (package body),
Silicon (chip), Copper (boundary-level for thin conducting layers).
"""
import jpype

JS = jpype.JArray(jpype.JString)
JI = jpype.JArray(jpype.JInt)

comp = model.component("comp1")

# --- 1. Aluminum — apply to ALL domains (pins are the majority) ----------
mat1 = comp.material().create("mat1", "Common")
mat1.label("Aluminum")
mat1.selection().all()
mat1.propertyGroup("def").set("thermalconductivity", JS(["237[W/(m*K)]"]))
mat1.propertyGroup("def").set("density", JS(["2700[kg/m^3]"]))
mat1.propertyGroup("def").set("heatcapacity", JS(["904[J/(kg*K)]"]))

# --- 2. FR4 Circuit Board — override board domain ------------------------
# Board is blk1: the large block at z = [-1.9, -0.9]
# Use a Ball selection centered in the board to find its domain
sel_board = comp.selection().create("sel_board", "Ball")
sel_board.set("entitydim", jpype.JInt(3))
sel_board.set("posx", "0")
sel_board.set("posy", "0")
sel_board.set("posz", "-1.4")   # center of board
sel_board.set("r", "0.1")

mat2 = comp.material().create("mat2", "Common")
mat2.label("FR4 (Circuit Board)")
mat2.selection().named("sel_board")
mat2.propertyGroup("def").set("thermalconductivity", JS(["0.3[W/(m*K)]"]))
mat2.propertyGroup("def").set("density", JS(["1900[kg/m^3]"]))
mat2.propertyGroup("def").set("heatcapacity", JS(["1369[J/(kg*K)]"]))

# --- 3. Plastic — override package body domain ---------------------------
# Package body is blk2: centered block at z = [-0.1, 0.1]
sel_pkg = comp.selection().create("sel_pkg", "Ball")
sel_pkg.set("entitydim", jpype.JInt(3))
sel_pkg.set("posx", "0")
sel_pkg.set("posy", "0")
sel_pkg.set("posz", "0")
sel_pkg.set("r", "0.1")

mat3 = comp.material().create("mat3", "Common")
mat3.label("Plastic")
mat3.selection().named("sel_pkg")
mat3.propertyGroup("def").set("thermalconductivity", JS(["0.2[W/(m*K)]"]))
mat3.propertyGroup("def").set("density", JS(["2700[kg/m^3]"]))
mat3.propertyGroup("def").set("heatcapacity", JS(["900[J/(kg*K)]"]))

# --- 4. Silicon — override chip domain -----------------------------------
# Chip is blk4: centered at z = [-0.05], size 3x1.5x0.1
sel_chip = comp.selection().create("sel_chip", "Ball")
sel_chip.set("entitydim", jpype.JInt(3))
sel_chip.set("posx", "0")
sel_chip.set("posy", "0")
sel_chip.set("posz", "-0.05")
sel_chip.set("r", "0.01")

mat4 = comp.material().create("mat4", "Common")
mat4.label("Silicon")
mat4.selection().named("sel_chip")
mat4.propertyGroup("def").set("thermalconductivity", JS(["130[W/(m*K)]"]))
mat4.propertyGroup("def").set("density", JS(["2329[kg/m^3]"]))
mat4.propertyGroup("def").set("heatcapacity", JS(["700[J/(kg*K)]"]))

# --- Boundary selections for physics and plots ----------------------------
# Voltage regulator: end face of board at x = -10
sel_vr = comp.selection().create("sel_vr", "Ball")
sel_vr.set("entitydim", jpype.JInt(2))
sel_vr.set("posx", "-10")
sel_vr.set("posy", "0")
sel_vr.set("posz", "-1.4")
sel_vr.set("r", "0.1")

# Ground plate: work plane boundary at z = -0.9
sel_gp = comp.selection().create("sel_gp", "Ball")
sel_gp.set("entitydim", jpype.JInt(2))
sel_gp.set("posx", "0")
sel_gp.set("posy", "0")
sel_gp.set("posz", "-0.9")
sel_gp.set("r", "0.1")

# Interconnect trace: work plane boundary at z = -0.1
sel_ic = comp.selection().create("sel_ic", "Ball")
sel_ic.set("entitydim", jpype.JInt(2))
sel_ic.set("posx", "-2.5")
sel_ic.set("posy", "0")
sel_ic.set("posz", "-0.1")
sel_ic.set("r", "0.1")

# --- 5. Copper — boundary-level for thin layers --------------------------
# Applied to work plane boundaries (ground plate + interconnect)
mat5 = comp.material().create("mat5", "Common")
mat5.label("Copper")
mat5.selection().geom("geom1", jpype.JInt(2))  # boundary-level
mat5.selection().all()  # all boundaries (thin layer physics will select specific ones)
mat5.propertyGroup("def").set("thermalconductivity", JS(["400[W/(m*K)]"]))
mat5.propertyGroup("def").set("density", JS(["8700[kg/m^3]"]))
mat5.propertyGroup("def").set("heatcapacity", JS(["385[J/(kg*K)]"]))

_result = {
    "step": "materials",
    "materials": ["Aluminum (all/pins)", "FR4 (board)", "Plastic (package)",
                  "Silicon (chip)", "Copper (boundaries)"],
    "status": "ok",
}
