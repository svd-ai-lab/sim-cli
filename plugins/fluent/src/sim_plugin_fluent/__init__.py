"""PyFluent driver plugin for sim.

Distributed as an out-of-tree plugin; discovered by sim via the
``sim.drivers`` entry-point group. Bundled skill files (under ``_skills/``)
are exposed via the ``sim.skills`` entry-point group.
"""
from importlib.resources import files

from .driver import PyFluentDriver

skills_dir = files(__name__) / "_skills"


plugin_info = {
    "name": "fluent",
    "summary": "Ansys Fluent driver and bundled skill for sim.",
    "homepage": "https://github.com/svd-ai-lab/sim-plugin-fluent",
    "license_class": "commercial",
    "solver_name": "fluent",
}

__all__ = ["PyFluentDriver", "skills_dir", "plugin_info"]
