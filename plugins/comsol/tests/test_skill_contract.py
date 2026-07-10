from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = (
    REPO_ROOT
    / "src"
    / "sim_plugin_comsol"
    / "_skills"
    / "comsol"
    / "SKILL.md"
)


def test_long_running_guidance_preserves_direct_comsol_paths() -> None:
    text = SKILL.read_text(encoding="utf-8")
    flat = " ".join(text.split())

    assert "## Long-running execution and recovery" in text
    assert "it does not prove COMSOL stopped" in flat
    assert "full command line, start time" in flat
    assert "Never terminate every `comsol` process by name" in flat
    assert "COMSOL-native checkpoint" in flat
    assert "restart rather than promising generic resume" in flat
    assert (
        "Do not require a fixed directory tree, a job manifest, or sim-cli" in flat
    )
    assert "Call `comsolbatch.exe` directly" in text
    assert "always run COMSOL in the background" not in text
