"""HyperMesh plugin for sim-cli."""
from importlib.resources import files

from .driver import HyperMeshDriver

skills_dir = files(__name__) / "_skills"

plugin_info = {
    "name": "hypermesh",
    "summary": "Private GUI collaboration driver for HyperMesh mesh workflows.",
    "homepage": "https://github.com/svd-ai-lab/sim-cli/tree/main/plugins/hypermesh",
    "solver_name": "hypermesh",
}

__all__ = ["HyperMeshDriver", "skills_dir", "plugin_info"]
