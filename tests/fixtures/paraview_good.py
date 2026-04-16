"""Minimal ParaView script -- create a sphere and print stats."""
import json
from paraview.simple import Sphere, Show, Render, GetActiveSource

sphere = Sphere(Radius=1.0)
Show(sphere)
Render()

print(json.dumps({
    "ok": True,
    "source_type": "Sphere",
    "radius": 1.0,
}))
