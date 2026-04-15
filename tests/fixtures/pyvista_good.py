"""Minimal pyvista script — create a sphere and compute stats."""
import json
import pyvista as pv

sphere = pv.Sphere(radius=1.0, theta_resolution=20, phi_resolution=20)
print(json.dumps({
    "ok": True,
    "n_points": int(sphere.n_points),
    "n_cells": int(sphere.n_cells),
    "bounds": list(map(float, sphere.bounds)),
}))
