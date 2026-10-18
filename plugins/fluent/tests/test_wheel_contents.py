"""Build the wheel and assert that bundled skill files ship."""
from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_wheel_contains_skills(tmp_path: Path) -> None:
    out_dir = tmp_path / "dist"
    out_dir.mkdir()

    proc = subprocess.run(
        [sys.executable, "-m", "build", "--no-isolation", "--wheel", "--outdir", str(out_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, f"build failed: {proc.stderr[-2000:]}"

    wheels = list(out_dir.glob("sim_plugin_fluent-*.whl"))
    assert len(wheels) == 1, f"expected one wheel, got {wheels}"

    with zipfile.ZipFile(wheels[0]) as zf:
        names = set(zf.namelist())

    required = {
        "sim_plugin_fluent/__init__.py",
        "sim_plugin_fluent/artifacts.py",
        "sim_plugin_fluent/driver.py",
        "sim_plugin_fluent/queries.py",
        "sim_plugin_fluent/_skills/fluent/SKILL.md",
        "sim_plugin_fluent/_skills/fluent/base/snippets/setup_partially_premixed_flamelet.py",
        "sim_plugin_fluent/_skills/fluent/base/snippets/write_pdf_table.py",
        "sim_plugin_fluent/_skills/fluent/base/snippets/read_case_pdf_data.py",
        "sim_plugin_fluent/_skills/fluent/base/snippets/inspect_reacting_bc_scalars.py",
    }
    missing = required - names
    assert not missing, f"missing from wheel: {missing}"
    assert not any("/skill_tests/" in name for name in names)
    assert not any("/_skills/fluent/tests/" in name for name in names)


def test_flamelet_skill_regression_text() -> None:
    skill_root = REPO_ROOT / "src" / "sim_plugin_fluent" / "_skills" / "fluent"
    task_templates = (skill_root / "base" / "reference" / "task_templates.md").read_text(
        encoding="utf-8"
    )
    acceptance = (skill_root / "base" / "reference" / "acceptance_checklists.md").read_text(
        encoding="utf-8"
    )

    assert "Partially Premixed Flamelet/PDF Table Run" in task_templates
    assert "write_pdf_cmd" in task_templates
    assert "read_case -> read_pdf -> read_data" in acceptance
    assert "sim-cli generic" not in task_templates
