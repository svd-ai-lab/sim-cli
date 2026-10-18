from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "src" / "sim_plugin_fluent" / "_skills" / "fluent"


def test_fluent_skill_chooses_control_path_without_mandating_sim_cli() -> None:
    text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert "Choose The Control Path" in text
    assert "Live sim session" in text
    assert "Direct PyFluent script" in text
    assert "File-side artifact review" in text
    assert "sdk/0.38/" in text
    assert "sdk/0.37/" in text
    assert "First, read" not in text
    assert "You are driving **Ansys Fluent** via sim-cli" not in text
    assert "sdk/pyfluent-0.38" not in text
    assert "sdk/pyfluent-0.37" not in text


def test_sim_specific_hard_constraints_are_scoped_to_live_sessions() -> None:
    text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

    scoped_heading = "Live Sim Session Constraints"
    assert scoped_heading in text
    scoped = text[text.index(scoped_heading):]
    assert "Do not call `pyfluent.launch_fluent()` inside a `uv run sim exec` snippet" in scoped
    assert "For direct PyFluent scripts, launch the session normally" in text


def test_qa_only_skill_specs_are_not_bundled() -> None:
    assert not (SKILL_ROOT / "skill_tests").exists()
    assert not (SKILL_ROOT / "tests").exists()


def test_long_running_guidance_preserves_direct_fluent_paths() -> None:
    text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    flat = " ".join(text.split())

    assert "## Long-running execution and recovery" in text
    assert "it does not prove Fluent stopped" in flat
    assert "full command line, start time" in flat
    assert (
        "Never terminate every `fluent`, `ansys`, or `cortex` process" in flat
    )
    assert "Fluent-native checkpoint" in flat
    assert "restart rather than promising generic resume" in flat
    assert (
        "Do not require a fixed directory tree, a job manifest, or sim-cli" in flat
    )
    assert "For direct PyFluent scripts, launch the session normally" in text
    assert "always run Fluent in the background" not in text
