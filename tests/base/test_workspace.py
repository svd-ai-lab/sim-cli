"""Workspace index and release identity boundaries."""
import importlib.util
from pathlib import Path

import pytest

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


def test_release_tag_selects_only_matching_package():
    release = load("release_package")
    assert release.select("abaqus-v0.1.4")["project"] == "plugins/abaqus"
    for tag, package in [("abaqus-v9.9.9", None), ("abaqus-v0.1.4", "fluent"), ("v0.1.4", None)]:
        with pytest.raises(ValueError):
            release.select(tag, package)


def test_bundled_skills_exclude_solver_result_artifacts():
    for file in (ROOT / "plugins").rglob("*"):
        if "_skills" not in file.parts or not file.is_file():
            continue
        assert file.suffix.lower() not in {".png", ".odb", ".sim", ".sim~", ".dat"}, file
        if "evidence" in file.parts:
            assert file.name == "README.md", file
