"""Ansys SpaceClaim skill package for sim/Codex workflows.

Importing this package is intentionally lightweight. SpaceClaim itself is a
desktop application, so availability and command support should be discovered
at task time through the bundled skill and probe script.
"""
from importlib.resources import files
from pathlib import Path


def _skills_dir():
    source_tree_skills = Path(__file__).resolve().parents[2] / "skills"
    if source_tree_skills.is_dir():
        return source_tree_skills
    return files(__name__) / "_skills"


skills_dir = _skills_dir()


plugin_info = {
    "name": "spaceclaim",
    "summary": "Ansys SpaceClaim CAD-preparation skill package for sim.",
    "homepage": "https://github.com/svd-ai-lab/sim-cli/tree/main/plugins/spaceclaim",
    "license_class": "commercial",
    "solver_name": "spaceclaim",
}


__all__ = ["skills_dir", "plugin_info"]
