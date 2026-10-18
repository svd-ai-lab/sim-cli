"""Structure tests for sim-agent-flotherm Phase A.

These tests verify the agent's reference material is complete and correct.
No Flotherm installation required — runs in any CI environment.

Design rationale (from spec §4):
    Structure tests enforce that the agent's reference material contains the
    right concepts before anyone attempts execution tests. A skill that passes
    structure tests but fails execution tests has an implementation defect.
    A skill that fails structure tests cannot even be used by an agent.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from conftest import AGENT_ROOT


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _read(rel: str) -> str:
    return (AGENT_ROOT / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# SKILL.md
# ---------------------------------------------------------------------------

class TestSkillMd:
    """SKILL.md must exist and describe the Phase A batch protocol correctly."""

    def test_skill_md_exists(self):
        assert (AGENT_ROOT / "skills/flotherm-sim/SKILL.md").exists(), \
            "skills/flotherm-sim/SKILL.md is missing"

    def test_skill_md_describes_batch_model(self):
        text = _read("skills/flotherm-sim/SKILL.md")
        assert "batch" in text.lower(), "SKILL.md must describe batch execution model"

    def test_skill_md_references_run_file(self):
        text = _read("skills/flotherm-sim/SKILL.md")
        assert "run_file" in text, "SKILL.md must reference driver.run_file"

    def test_skill_md_has_input_validation_section(self):
        text = _read("skills/flotherm-sim/SKILL.md")
        assert "input" in text.lower() and "validat" in text.lower(), \
            "SKILL.md must have an input validation section"

    def test_skill_md_distinguishes_exit_code_from_completion(self):
        text = _read("skills/flotherm-sim/SKILL.md")
        assert "exit_code" in text, "SKILL.md must mention exit_code"
        # Must warn that exit_code=0 alone is not enough
        assert "not" in text.lower() or "alone" in text.lower(), \
            "SKILL.md must clarify that exit_code=0 alone does not mean success"

    def test_skill_md_has_when_to_stop_section(self):
        text = _read("skills/flotherm-sim/SKILL.md")
        assert "stop" in text.lower() or "escalat" in text.lower(), \
            "SKILL.md must describe when to stop and escalate"

    def test_skill_md_has_phase_a_scope_boundary(self):
        text = _read("skills/flotherm-sim/SKILL.md")
        # Must be clear about what Phase A does NOT cover
        assert "phase" in text.lower() or "scope" in text.lower(), \
            "SKILL.md must define scope boundaries (Phase A vs future phases)"


# ---------------------------------------------------------------------------
# reference/task_templates.md
# ---------------------------------------------------------------------------

class TestTaskTemplates:
    """task_templates.md must cover the batch .pack workflow."""

    def test_task_templates_exists(self):
        assert (AGENT_ROOT / "reference/task_templates.md").exists()

    def test_template_covers_pack_file(self):
        text = _read("reference/task_templates.md")
        assert ".pack" in text, "task_templates.md must cover .pack batch execution"

    def test_template_has_required_inputs_table(self):
        text = _read("reference/task_templates.md")
        assert "Required" in text and "Input" in text, \
            "task_templates.md must have a Required Inputs section"

    def test_template_includes_lint_step(self):
        text = _read("reference/task_templates.md")
        assert "lint" in text.lower(), \
            "task_templates.md must include a lint/validate step"

    def test_template_includes_connect_step(self):
        text = _read("reference/task_templates.md")
        assert "connect" in text.lower(), \
            "task_templates.md must include a connect/check-installation step"

    def test_template_has_completion_condition(self):
        text = _read("reference/task_templates.md")
        assert "completion" in text.lower() or "complete" in text.lower(), \
            "task_templates.md must define a completion condition"

    def test_template_covers_smoke_test(self):
        text = _read("reference/task_templates.md")
        assert "smoke" in text.lower() or "connectivity" in text.lower(), \
            "task_templates.md must include a smoke/connectivity test template"


# ---------------------------------------------------------------------------
# reference/acceptance_checklists.md
# ---------------------------------------------------------------------------

class TestAcceptanceChecklists:
    """acceptance_checklists.md must define what 'task complete' means for batch runs."""

    def test_acceptance_checklists_exists(self):
        assert (AGENT_ROOT / "reference/acceptance_checklists.md").exists()

    def test_checklist_has_required_markers(self):
        text = _read("reference/acceptance_checklists.md")
        assert "[REQUIRED]" in text, \
            "acceptance_checklists.md must use [REQUIRED] markers"

    def test_checklist_covers_exit_code(self):
        text = _read("reference/acceptance_checklists.md")
        assert "exit_code" in text

    def test_checklist_covers_stdout(self):
        text = _read("reference/acceptance_checklists.md")
        assert "stdout" in text

    def test_checklist_covers_duration(self):
        text = _read("reference/acceptance_checklists.md")
        assert "duration" in text

    def test_checklist_clarifies_exit_code_not_sufficient(self):
        text = _read("reference/acceptance_checklists.md")
        # Must state that exit_code alone is not sufficient for completion claim
        lower = text.lower()
        assert ("alone" in lower or "not sufficient" in lower or "does not mean" in lower), \
            "acceptance_checklists.md must clarify exit_code alone is insufficient"


# ---------------------------------------------------------------------------
# reference/runtime_patterns.md
# ---------------------------------------------------------------------------

class TestRuntimePatterns:
    """runtime_patterns.md must describe the Phase A control loop."""

    def test_runtime_patterns_exists(self):
        assert (AGENT_ROOT / "reference/runtime_patterns.md").exists()

    def test_patterns_cover_validate_step(self):
        text = _read("reference/runtime_patterns.md")
        assert "lint" in text.lower() or "validat" in text.lower()

    def test_patterns_cover_failure_handling(self):
        text = _read("reference/runtime_patterns.md")
        assert "fail" in text.lower()

    def test_patterns_cover_report_step(self):
        text = _read("reference/runtime_patterns.md")
        assert "report" in text.lower()


# ---------------------------------------------------------------------------
# Execution test specs
# ---------------------------------------------------------------------------

class TestExecutionTestSpecs:
    """The execution test specification files must exist."""

    def test_execution_test_protocol_exists(self):
        assert (AGENT_ROOT / "skills/flotherm-sim/tests/execution_test_protocol.md").exists()

    def test_execution_test_cases_exists(self):
        assert (AGENT_ROOT / "skills/flotherm-sim/tests/execution_test_cases_v1.md").exists()

    def test_execution_test_cases_has_at_least_one_case(self):
        text = _read("skills/flotherm-sim/tests/execution_test_cases_v1.md")
        assert "EX-" in text, "execution_test_cases_v1.md must define at least one EX-XX case"

    def test_execution_test_protocol_defines_pass_criteria(self):
        text = _read("skills/flotherm-sim/tests/execution_test_protocol.md")
        assert "pass" in text.lower() or "Pass" in text, \
            "execution_test_protocol.md must define pass/fail criteria"
