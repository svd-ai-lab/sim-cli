"""Ansys Workbench driver plugin for sim-cli.

Distributed as an out-of-tree plugin; discovered by sim-cli via the
``sim.drivers`` entry-point group. Bundled skill files (under ``_skills/``)
are exposed via the ``sim.skills`` entry-point group.

Dual-mode execution: PyWorkbench SDK (``ansys-workbench-core``) preferred,
RunWB2 batch fallback when SDK is unavailable or fails.
"""
from importlib.resources import files

from .driver import WorkbenchDriver

skills_dir = files(__name__) / "_skills"

__all__ = ["WorkbenchDriver", "skills_dir"]
