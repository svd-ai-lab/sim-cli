"""Workspace index and release identity boundaries."""
import importlib.util
from pathlib import Path
import tomllib

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_index_preserves_package_entry_points():
    index = load("workspace").plugin_index()
    assert len(index["plugins"]) == 11
    for plugin in index["plugins"]:
        assert plugin["package"] == "sim-plugin-" + plugin["solver"]
        assert "sim.skills" in plugin["entry_points"]
        assert plugin["path"] == "plugins/" + plugin["solver"]


def test_index_install_spec_follows_pypi_flag():
    for plugin in load("workspace").plugin_index()["plugins"]:
        document = tomllib.loads((ROOT / plugin["path"] / "pyproject.toml").read_text(encoding="utf-8"))
        if document.get("tool", {}).get("sim", {}).get("pypi", True):
            assert plugin["install_spec"] == plugin["package"]
        else:
            assert plugin["install_spec"].endswith("#subdirectory=" + plugin["path"])


def test_release_tag_selects_only_matching_package():
    release = load("release_package")
    version = tomllib.loads((ROOT / "plugins/abaqus/pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    assert release.select(f"abaqus-v{version}")["project"] == "plugins/abaqus"
    for tag, package in [("abaqus-v999.0.0", None), (f"abaqus-v{version}", "fluent"), (f"v{version}", None)]:
        with pytest.raises(ValueError):
            release.select(tag, package)


def test_bundled_skills_exclude_solver_result_artifacts():
    for file in (ROOT / "plugins").rglob("*"):
        if "_skills" not in file.parts or not file.is_file():
            continue
        assert file.suffix.lower() not in {".png", ".odb", ".sim", ".sim~", ".dat"}, file
        if "evidence" in file.parts:
            assert file.name == "README.md", file


def test_skill_frontmatter_is_valid_yaml():
    for file in [*(ROOT / "plugins").rglob("SKILL.md"), *(ROOT / "src/sim/_skills").rglob("SKILL.md")]:
        text = file.read_text(encoding="utf-8")
        assert text.startswith("---"), file
        metadata = yaml.safe_load(text.split("---", 2)[1])
        assert metadata["name"] and metadata["description"], file
