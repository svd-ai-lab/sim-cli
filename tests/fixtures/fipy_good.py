"""Minimal FiPy script — 1D mesh + variable."""
import json
from fipy import CellVariable, Grid1D
mesh = Grid1D(nx=10, dx=1.0)
phi = CellVariable(name='phi', mesh=mesh, value=0.0)
print(json.dumps({"ok": True, "n_cells": int(mesh.numberOfCells)}))
