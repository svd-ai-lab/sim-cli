"""Simcenter Flotherm driver plugin for sim-cli.

Distributed as an out-of-tree plugin; discovered by sim-cli via the
``sim.drivers`` entry-point group. Bundled skill files (under ``_skills/``)
are exposed via the ``sim.skills`` entry-point group.
"""
from importlib.resources import files

from .driver import FlothermDriver

skills_dir = files(__name__) / "_skills"


plugin_info = {
    "name": "flotherm",
    "summary": "Driver plugin for sim-cli.",
    "homepage": "https://github.com/svd-ai-lab/sim-plugin-flotherm",
    "license_class": "commercial",
    "solver_name": "flotherm",
}

__all__ = ["FlothermDriver", "skills_dir", "plugin_info"]
