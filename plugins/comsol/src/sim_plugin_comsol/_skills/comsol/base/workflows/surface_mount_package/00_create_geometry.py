"""Create 3D geometry for surface-mount package on a circuit board.

Based on COMSOL Application Library model 847:
Heat Transfer in a Surface-Mount Package for a Silicon Chip.

Geometry (mm units): PC board, chip package body, 16 gull-wing pins
(simplified as L-shaped blocks), silicon chip, ground-plate and
interconnect work planes for thin copper layers.
"""
import jpype

JD = jpype.JArray(jpype.JDouble)
JI = jpype.JArray(jpype.JInt)
JS = jpype.JArray(jpype.JString)

model.label("Surface Mount Package")

comp = model.component().create("comp1", True)
geom = model.component("comp1").geom().create("geom1", 3)
geom.lengthUnit("mm")

# --- PC Board (20 x 10 x 1 mm) ------------------------------------------
blk1 = geom.create("blk1", "Block")
blk1.set("size", JD([20.0, 10.0, 1.0]))
blk1.set("pos", JD([-10.0, -5.0, -1.9]))
blk1.label("PC Board")

# --- Chip Package body (9.9 x 3.9 x 0.2 mm, centered) ------------------
blk2 = geom.create("blk2", "Block")
blk2.set("size", JD([9.9, 3.9, 0.2]))
blk2.set("base", "center")
blk2.label("Chip Package Body")

# --- Gull-wing pins (simplified L-shape: horizontal + vertical leg) ------
# 8 pins per side, 1.27 mm pitch, starting at x = -4.645
# Each pin: horizontal part on package + vertical leg down to board
pin_tags = []
for i in range(8):
    x0 = -4.645 + i * 1.27
    for side, y_sign in [("n", 1), ("s", -1)]:
        tag_h = f"pin_{side}{i}_h"
        tag_v = f"pin_{side}{i}_v"

        # Horizontal part (on package body, extends outward)
        ph = geom.create(tag_h, "Block")
        ph.set("size", JD([0.4, 0.5, 0.2]))
        ph.set("pos", JD([x0, y_sign * 1.95 - (0.5 if y_sign < 0 else 0), -0.1]))
        ph.label(f"Pin {side.upper()}{i} horiz")

        # Vertical leg (bends down to board surface)
        pv = geom.create(tag_v, "Block")
        pv.set("size", JD([0.4, 0.26, 0.8]))
        pv.set("pos", JD([x0, y_sign * 2.45 - (0.26 if y_sign < 0 else 0), -0.9]))
        pv.label(f"Pin {side.upper()}{i} vert")

        pin_tags.extend([tag_h, tag_v])

# Union all pin parts
uni_pins = geom.create("uni_pins", "Union")
uni_pins.selection("input").set(JS(pin_tags))
uni_pins.set("intbnd", False)
uni_pins.label("All Pins")

# --- Silicon Chip (3 x 1.5 x 0.1 mm, centered at z=-0.05) ---------------
blk4 = geom.create("blk4", "Block")
blk4.set("size", JD([3.0, 1.5, 0.1]))
blk4.set("base", "center")
blk4.set("pos", JD([0.0, 0.0, -0.05]))
blk4.label("Silicon Chip")

# --- Work Plane 1: Ground plate (inside PC board at z = -0.9) -----------
wp1 = geom.create("wp1", "WorkPlane")
wp1.set("quickz", -0.9)
wp1.label("Ground Plate Plane")
wp1r = wp1.geom()
r1 = wp1r.create("r1", "Rectangle")
r1.set("size", JD([6.0, 4.0]))
r1.set("pos", JD([-3.0, -2.0]))
r1.label("Ground Plate")

# --- Work Plane 2: Interconnect trace (at z = -0.1, under chip) ----------
wp2 = geom.create("wp2", "WorkPlane")
wp2.set("quickz", -0.1)
wp2.label("Interconnect Plane")
wp2r = wp2.geom()

# Interconnect L-shape (outer rect minus inner rect)
ri1 = wp2r.create("ri1", "Rectangle")
ri1.set("size", JD([4.145, 2.15]))
ri1.set("pos", JD([-4.645, -1.95]))
ri2 = wp2r.create("ri2", "Rectangle")
ri2.set("size", JD([3.745, 1.75]))
ri2.set("pos", JD([-4.245, -1.95]))
dif1 = wp2r.create("dif1", "Difference")
dif1.selection("input").set("ri1")
dif1.selection("input2").set("ri2")
dif1.label("Interconnect Trace")

# --- Build all geometry --------------------------------------------------
geom.run("fin")

_result = {
    "step": "geometry",
    "description": "Surface-mount package: board + package + 16 pins + chip + work planes",
    "length_unit": "mm",
    "status": "ok",
}
