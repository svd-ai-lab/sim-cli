"""COMSOL Multiphysics driver plugin for sim-cli.

Distributed as an out-of-tree plugin; discovered by sim-cli via the
``sim.drivers`` entry-point group. Bundled skill files (under ``_skills/``)
are exposed via the ``sim.skills`` entry-point group.
"""
from importlib.resources import files

from .driver import ComsolDriver

skills_dir = files(__name__) / "_skills"


plugin_info = {
    "name": "comsol",
    "summary": "Driver plugin for sim-cli.",
    "homepage": "https://github.com/svd-ai-lab/sim-plugin-comsol",
    "license_class": "commercial",
    "solver_name": "comsol",
}

__all__ = ["ComsolDriver", "skills_dir", "plugin_info"]
