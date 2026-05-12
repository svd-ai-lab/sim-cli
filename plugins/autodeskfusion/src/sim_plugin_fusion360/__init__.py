"""Autodesk Fusion 360 driver plugin for sim."""
from importlib.resources import files

from .driver import Fusion360Driver

skills_dir = files(__name__) / "_skills"

plugin_info = {
    "name": "fusion360",
    "summary": "Autodesk Fusion 360 live-session bridge and bundled skill for sim.",
    "homepage": "https://github.com/svd-ai-lab/sim-plugin-fusion360",
    "license_class": "commercial",
    "solver_name": "Autodesk Fusion 360",
}

__all__ = ["Fusion360Driver", "skills_dir", "plugin_info"]
