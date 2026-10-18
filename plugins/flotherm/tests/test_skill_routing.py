"""Regression tests for runtime-first routing in the bundled Flotherm skill."""

from pathlib import Path


SKILL = (
    Path(__file__).parents[1]
    / "src"
    / "sim_plugin_flotherm"
    / "_skills"
    / "flotherm"
    / "SKILL.md"
)


def _skill_text() -> str:
    return SKILL.read_text(encoding="utf-8")


def test_skill_does_not_assume_sim_cli_connection() -> None:
    text = _skill_text()
    assert "You are connected" not in text
    assert "do not assume either is installed or connected" in text


def test_skill_routes_by_capability_and_task() -> None:
    text = _skill_text()
    assert "Start with capability discovery" in text
    assert "Native `translator.exe` + `solexe.exe`" in text
    assert "sim-cli GUI automation" in text
    assert "Do not install or download sim-cli merely" in text


def test_skill_requires_consent_before_installing_sim_cli() -> None:
    text = _skill_text()
    assert "get the user's approval before downloading" in text
    assert "Do not silently use a repository `main` branch" in text


def test_skill_bounds_equivalent_retries() -> None:
    text = _skill_text()
    assert "Do not repeat an equivalent `exec` call" in text
    assert "one bounded diagnostic cycle" in text
