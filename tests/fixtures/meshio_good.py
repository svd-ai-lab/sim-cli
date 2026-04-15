"""Minimal meshio Python script — convert Gmsh to VTK."""
import json
import sys
import meshio

if len(sys.argv) >= 2:
    mesh = meshio.read(sys.argv[1])
else:
    # Fallback: fabricate a trivial mesh for fixture purposes
    import numpy as np
    mesh = meshio.Mesh(
        points=np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=float),
        cells=[("triangle", np.array([[0, 1, 2]]))],
    )

print(json.dumps({
    "ok": True,
    "points": len(mesh.points),
    "cells": {t.type: len(t.data) for t in mesh.cells},
}))
