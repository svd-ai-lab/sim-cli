from __future__ import annotations

import sim_plugin_spaceclaim


def test_skills_dir_contains_spaceclaim_skill() -> None:
    skill = sim_plugin_spaceclaim.skills_dir / "spaceclaim" / "SKILL.md"

    assert skill.is_file()
    text = skill.read_text(encoding="utf-8")
    assert "name: spaceclaim" in text
    assert "SpaceClaim" in text
    assert "[TODO" not in text


def test_plugin_info_is_lightweight() -> None:
    assert sim_plugin_spaceclaim.plugin_info["name"] == "spaceclaim"
    assert sim_plugin_spaceclaim.plugin_info["solver_name"] == "spaceclaim"
