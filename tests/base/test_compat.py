"""Tests for the skills layering surface in sim.compat.

Three groups:

  TestProfileFields           — `active_sdk_layer` / `active_solver_layer`
                                round-trip through compatibility.yaml
  TestVerifySkillsLayout      — `verify_skills_layout()` walks declared
                                profiles and reports on-disk mismatches
  TestSkillsBlockForProfile   — `skills_block_for_profile()` builds the
                                dict that /connect returns to the agent

All tests use synthetic temp trees so they do NOT depend on the sibling
sim-skills repo being present.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml


def _write_compat(driver_dir: Path, body: dict) -> None:
    driver_dir.mkdir(parents=True, exist_ok=True)
    (driver_dir / "compatibility.yaml").write_text(
        yaml.safe_dump(body, sort_keys=False), encoding="utf-8"
    )


def _build_synthetic_skills_tree(root: Path) -> None:
    """Create a complete fluent skill bundle:

        <root>/fluent/SKILL.md
        <root>/fluent/base/reference/concepts.md
        <root>/fluent/sdk/0.38/reference/api.md
        <root>/fluent/solver/25.2/known_issues.md
    """
    fluent = root / "fluent"
    (fluent / "base" / "reference").mkdir(parents=True)
    (fluent / "base" / "reference" / "concepts.md").write_text("# concepts\n")
    (fluent / "sdk" / "0.38" / "reference").mkdir(parents=True)
    (fluent / "sdk" / "0.38" / "reference" / "api.md").write_text("# api 0.38\n")
    (fluent / "solver" / "25.2").mkdir(parents=True)
    (fluent / "solver" / "25.2" / "known_issues.md").write_text("# 25R2\n")
    (fluent / "SKILL.md").write_text("# fluent skill index\n")


class TestProfileFields(unittest.TestCase):
    """active_sdk_layer / active_solver_layer round-trip through the loader."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_profile_loads_active_layer_fields(self):
        from sim.compat import load_compatibility, load_compatibility as _lc
        _lc.cache_clear()
        _write_compat(self.tmp, {
            "driver": "fluent",
            "sdk_package": "ansys-fluent-core",
            "profiles": [{
                "name": "pyfluent_0_38_modern",
                "sdk": ">=0.38,<0.39",
                "solver_versions": ["25.2"],
                "active_sdk_layer": "0.38",
                "active_solver_layer": "25.2",
            }],
        })
        compat = load_compatibility(self.tmp)
        p = compat.profiles[0]
        self.assertEqual(p.active_sdk_layer, "0.38")
        self.assertEqual(p.active_solver_layer, "25.2")

    def test_profile_active_layers_default_to_none(self):
        from sim.compat import load_compatibility
        load_compatibility.cache_clear()
        _write_compat(self.tmp, {
            "driver": "openfoam",
            "profiles": [{
                "name": "openfoam_v2406",
                "solver_versions": ["v2406"],
            }],
        })
        compat = load_compatibility(self.tmp)
        p = compat.profiles[0]
        self.assertIsNone(p.active_sdk_layer)
        self.assertIsNone(p.active_solver_layer)


def _profile(name="p", sdk_layer=None, solver_layer=None):
    """Construct a Profile by hand for verify-skills tests, bypassing yaml."""
    from sim.compat import Profile
    return Profile(
        name=name,
        solver_versions=("dummy",),
        sdk=None,
        notes="",
        active_sdk_layer=sdk_layer,
        active_solver_layer=solver_layer,
    )


class TestVerifySkillsLayout(unittest.TestCase):
    """verify_skills_layout() walks (driver, profile) pairs and audits the tree."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        _build_synthetic_skills_tree(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_passes_on_complete_synthetic_tree(self):
        from sim.compat import verify_skills_layout
        result = verify_skills_layout(
            self.tmp,
            profiles=[("fluent", _profile("pyfluent_0_38_modern", "0.38", "25.2"))],
        )
        self.assertEqual(result, [])

    def test_flags_missing_skill_md(self):
        from sim.compat import verify_skills_layout
        (self.tmp / "fluent" / "SKILL.md").unlink()
        result = verify_skills_layout(
            self.tmp,
            profiles=[("fluent", _profile("p", "0.38", "25.2"))],
        )
        self.assertTrue(any("SKILL.md" in m for m in result), result)

    def test_flags_missing_base(self):
        from sim.compat import verify_skills_layout
        shutil.rmtree(self.tmp / "fluent" / "base")
        result = verify_skills_layout(
            self.tmp,
            profiles=[("fluent", _profile("p", "0.38", "25.2"))],
        )
        self.assertTrue(any("base" in m for m in result), result)

    def test_flags_missing_sdk_layer(self):
        from sim.compat import verify_skills_layout
        result = verify_skills_layout(
            self.tmp,
            profiles=[("fluent", _profile("p", "0.99", "25.2"))],
        )
        self.assertTrue(any("sdk/0.99" in m for m in result), result)

    def test_flags_missing_solver_layer(self):
        from sim.compat import verify_skills_layout
        result = verify_skills_layout(
            self.tmp,
            profiles=[("fluent", _profile("p", "0.38", "99.99"))],
        )
        self.assertTrue(any("solver/99.99" in m for m in result), result)

    def test_skips_unset_layers(self):
        """A profile with active_*_layer=None must NOT trigger sdk/solver checks
        — only the SKILL.md and base/ existence are verified."""
        from sim.compat import verify_skills_layout
        # Delete sdk and solver dirs entirely; the profile doesn't reference them.
        shutil.rmtree(self.tmp / "fluent" / "sdk")
        shutil.rmtree(self.tmp / "fluent" / "solver")
        result = verify_skills_layout(
            self.tmp,
            profiles=[("fluent", _profile("p", None, None))],
        )
        self.assertEqual(result, [])

    def test_flags_missing_driver_dir(self):
        from sim.compat import verify_skills_layout
        result = verify_skills_layout(
            self.tmp,
            profiles=[("nonexistent", _profile("p", None, None))],
        )
        self.assertTrue(any("nonexistent" in m for m in result), result)


class TestSkillsBlockForProfile(unittest.TestCase):
    """skills_block_for_profile builds the dict /connect returns to the agent."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        _build_synthetic_skills_tree(self.tmp)
        self._saved = os.environ.pop("SIM_SKILLS_ROOT", None)

    def tearDown(self):
        shutil.rmtree(self.tmp)
        if self._saved is not None:
            os.environ["SIM_SKILLS_ROOT"] = self._saved
        else:
            os.environ.pop("SIM_SKILLS_ROOT", None)

    def test_returns_full_block_when_root_and_profile_present(self):
        from sim.compat import skills_block_for_profile
        os.environ["SIM_SKILLS_ROOT"] = str(self.tmp)
        block = skills_block_for_profile(
            "fluent", _profile("pyfluent_0_38_modern", "0.38", "25.2")
        )
        self.assertEqual(Path(block["root"]), (self.tmp / "fluent").resolve())
        self.assertEqual(Path(block["index"]), (self.tmp / "fluent" / "SKILL.md").resolve())
        self.assertEqual(block["active_sdk_layer"], "0.38")
        self.assertEqual(block["active_solver_layer"], "25.2")
        self.assertNotIn("hint", block)

    def test_returns_hint_when_root_absent(self):
        from sim.compat import skills_block_for_profile
        # No env var, no sibling tree (we're in a tmp cwd implicitly)
        os.environ["SIM_SKILLS_ROOT"] = str(self.tmp / "does-not-exist")
        block = skills_block_for_profile(
            "fluent", _profile("p", "0.38", "25.2")
        )
        self.assertIsNone(block["root"])
        self.assertIsNone(block["index"])
        self.assertIn("hint", block)
        self.assertIn("SIM_SKILLS_ROOT", block["hint"])

    def test_layers_null_when_profile_is_none(self):
        from sim.compat import skills_block_for_profile
        os.environ["SIM_SKILLS_ROOT"] = str(self.tmp)
        block = skills_block_for_profile("fluent", None)
        self.assertEqual(Path(block["root"]), (self.tmp / "fluent").resolve())
        self.assertIsNone(block["active_sdk_layer"])
        self.assertIsNone(block["active_solver_layer"])

    def test_root_none_when_driver_dir_absent(self):
        """skills root resolves, but the driver subdir is missing — root
        should still be returned (so the LLM can see the parent path) but
        index should be None."""
        from sim.compat import skills_block_for_profile
        os.environ["SIM_SKILLS_ROOT"] = str(self.tmp)
        block = skills_block_for_profile(
            "nonexistent_driver", _profile("p", None, None)
        )
        # Driver subdir doesn't exist → root is None to signal "nothing usable"
        self.assertIsNone(block["root"])
        self.assertIn("hint", block)

    def test_falls_back_to_plugin_bundled_skills(self):
        from sim.compat import skills_block_for_profile

        os.environ["SIM_SKILLS_ROOT"] = str(self.tmp / "does-not-exist")
        plugin_skill = self.tmp / "plugin-driver"
        plugin_skill.mkdir()
        (plugin_skill / "SKILL.md").write_text("# plugin skill\n", encoding="utf-8")

        with patch("sim.plugins.skills_dir_for", return_value=plugin_skill):
            block = skills_block_for_profile("plugin-driver", _profile("p", None, "v1"))

        self.assertEqual(Path(block["root"]), plugin_skill)
        self.assertEqual(Path(block["index"]), plugin_skill / "SKILL.md")
        self.assertIsNone(block["active_sdk_layer"])
        self.assertEqual(block["active_solver_layer"], "v1")
        self.assertNotIn("hint", block)


class TestConnectIncludesSkillsBlock(unittest.TestCase):
    """End-to-end: /connect response carries the skills block.

    Mocks the driver and matlab.engine path so the test runs without any
    real solver installed.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        _build_synthetic_skills_tree(self.tmp)
        # Add a comsol driver dir so /connect can resolve a profile for it
        comsol = self.tmp / "comsol"
        (comsol / "base").mkdir(parents=True)
        (comsol / "SKILL.md").write_text("# comsol skill index\n")
        self._saved = os.environ.pop("SIM_SKILLS_ROOT", None)
        os.environ["SIM_SKILLS_ROOT"] = str(self.tmp)

        # Reset server state between tests (multi-session registry)
        from sim import server
        server._sessions.clear()

    def tearDown(self):
        shutil.rmtree(self.tmp)
        if self._saved is not None:
            os.environ["SIM_SKILLS_ROOT"] = self._saved
        else:
            os.environ.pop("SIM_SKILLS_ROOT", None)
        from sim import server
        server._sessions.clear()

    def test_connect_response_carries_skills_block(self):
        from fastapi.testclient import TestClient
        from sim import server
        from sim.compat import load_compatibility

        load_compatibility.cache_clear()

        # Stub the comsol driver so launch() doesn't actually spawn COMSOL
        class _StubDriver:
            supports_session = True

            def launch(self, **kwargs):
                return {"ok": True, "session_id": "stub-sid"}

        original_get_driver = None
        try:
            from sim import drivers as drivers_mod
            original_get_driver = drivers_mod.get_driver
            drivers_mod.get_driver = lambda name: _StubDriver() if name == "comsol" else None
        except Exception:
            self.skipTest("sim.drivers not importable")

        try:
            client = TestClient(server.app)
            r = client.post("/connect", json={
                "solver": "comsol",
                "mode": "solver",
                "ui_mode": "no_gui",
                "processors": 1,
            })
            self.assertEqual(r.status_code, 200, r.text)
            data = r.json()["data"]
            self.assertIn("skills", data)
            skills = data["skills"]
            # comsol driver dir exists in our synthetic tree
            self.assertEqual(Path(skills["root"]), (self.tmp / "comsol").resolve())
            self.assertEqual(Path(skills["index"]), (self.tmp / "comsol" / "SKILL.md").resolve())
            # comsol's real compat.yaml has no active layer fields yet → both null
            self.assertIsNone(skills["active_sdk_layer"])
            self.assertIsNone(skills["active_solver_layer"])
        finally:
            if original_get_driver is not None:
                drivers_mod.get_driver = original_get_driver
            # Cleanup any lingering session
            server._sessions.clear()

    def test_connect_response_skills_root_none_when_tree_absent(self):
        from fastapi.testclient import TestClient
        from sim import server
        from sim.compat import load_compatibility

        load_compatibility.cache_clear()
        os.environ["SIM_SKILLS_ROOT"] = str(self.tmp / "does-not-exist")

        class _StubDriver:
            supports_session = True

            def launch(self, **kwargs):
                return {"ok": True, "session_id": "stub-sid"}

        from sim import drivers as drivers_mod
        original = drivers_mod.get_driver
        drivers_mod.get_driver = lambda name: _StubDriver() if name == "comsol" else None

        try:
            client = TestClient(server.app)
            r = client.post("/connect", json={
                "solver": "comsol",
                "mode": "solver",
                "ui_mode": "no_gui",
                "processors": 1,
            })
            self.assertEqual(r.status_code, 200, r.text)
            skills = r.json()["data"]["skills"]
            self.assertIsNone(skills["root"])
            self.assertIn("hint", skills)
        finally:
            drivers_mod.get_driver = original
            server._sessions.clear()


if __name__ == "__main__":
    unittest.main()
