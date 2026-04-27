"""Ansys Mechanical (PyMechanical) driver plugin for sim-cli.

Distributed as an out-of-tree plugin; discovered by sim-cli via the
``sim.drivers`` entry-point group. Bundled skill files (under ``_skills/``)
are exposed via the ``sim.skills`` entry-point group.
"""
from importlib.resources import files

from .driver import MechanicalDriver

skills_dir = files(__name__) / "_skills"

__all__ = ["MechanicalDriver", "skills_dir"]
