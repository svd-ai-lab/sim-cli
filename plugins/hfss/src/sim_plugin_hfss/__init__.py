"""Ansys HFSS driver plugin for sim-cli.

The package is discovered by sim-cli through entry points. Importing it must
stay safe on machines without AEDT or PyAEDT; the driver imports PyAEDT lazily
only when a runtime operation needs it.
"""
from importlib.resources import files

from .driver import HfssDriver

skills_dir = files(__name__) / "_skills"


plugin_info = {
    "name": "hfss",
    "summary": "Ansys HFSS 3D driver plugin for sim-cli.",
    "homepage": "https://github.com/svd-ai-lab/sim-plugin-hfss",
    "license_class": "commercial",
    "solver_name": "hfss",
}

__all__ = ["HfssDriver", "skills_dir", "plugin_info"]
