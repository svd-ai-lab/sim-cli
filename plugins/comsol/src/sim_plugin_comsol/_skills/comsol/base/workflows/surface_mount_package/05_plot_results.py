"""Create temperature visualisation plots.

Three plot groups matching the COMSOL Application Library model:
  1. Surface temperature on the full assembly
  2. Temperature slices (ZX planes) through the package
  3. Chip bottom-surface temperature detail
"""
res = model.result()

# --- Plot 1: Full-assembly surface temperature ---------------------------
pg1 = res.create("pg1", "PlotGroup3D")
pg1.label("Temperature (Surface)")
s1 = pg1.create("surf1", "Surface")
s1.set("expr", "T")
s1.set("unit", "degC")
s1.set("colortable", "HeatCameraLight")
pg1.run()

# --- Plot 2: Temperature slices (ZX planes) ------------------------------
pg2 = res.create("pg2", "PlotGroup3D")
pg2.label("Temperature (Slices)")
sl = pg2.create("slc1", "Slice")
sl.set("expr", "T")
sl.set("unit", "degC")
sl.set("quickplane", "zx")
sl.set("colortable", "HeatCameraLight")
pg2.run()

# --- Plot 3: Chip surface temperature ------------------------------------
# Full surface plot — zoom into chip area in the GUI for the detail view
pg3 = res.create("pg3", "PlotGroup3D")
pg3.label("Temperature (Chip Surface)")
s3 = pg3.create("surf1", "Surface")
s3.set("expr", "T")
s3.set("unit", "degC")
s3.set("colortable", "HeatCameraLight")
pg3.run()

# Save model
import os
model.save(os.path.join(os.environ.get("USERPROFILE", "C:/Users/jiwei"), "Desktop", "surface_mount_package.mph"))

_result = {
    "step": "plot",
    "plots": [
        "Temperature (Surface)",
        "Temperature (Slices)",
        "Temperature (Chip Surface)",
    ],
    "status": "ok",
}
