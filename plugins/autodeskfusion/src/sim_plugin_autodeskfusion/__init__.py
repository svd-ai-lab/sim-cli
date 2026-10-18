"""Autodesk Fusion driver plugin for sim."""
from importlib.resources import files

from .driver import AutodeskFusionDriver

skills_dir = files(__name__) / "_skills"

plugin_info = {
    "name": "autodeskfusion",
    "summary": "Autodesk Fusion official-MCP driver and bundled skill for sim.",
    "homepage": "https://github.com/svd-ai-lab/sim-plugin-autodeskfusion",
    "license_class": "commercial",
    "solver_name": "Autodesk Fusion",
}

__all__ = ["AutodeskFusionDriver", "skills_dir", "plugin_info"]
