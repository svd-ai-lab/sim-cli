"""Minimal well-formed PyMAPDL script (fixture)."""
from ansys.mapdl.core import launch_mapdl

mapdl = launch_mapdl()
mapdl.prep7()
mapdl.et(1, "BEAM188")
mapdl.solution()
mapdl.exit()
print('{"ok": true}')
