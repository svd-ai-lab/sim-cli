"""ParaView script that uses Interact() -- should warn in batch."""
from paraview.simple import Sphere, Show, Render, Interact

sphere = Sphere()
Show(sphere)
Render()
Interact()
