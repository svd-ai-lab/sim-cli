"""Opt-in smoke coverage for a real AEDT/HFSS installation.

This test is intentionally skipped in ordinary CI. Enable it on a machine with
AEDT available by setting ``SIM_HFSS_RUN_INTEGRATION=1`` when preparing a release.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sim_plugin_hfss import HfssDriver


if os.environ.get("SIM_HFSS_RUN_INTEGRATION") != "1":
    pytest.skip(
        "set SIM_HFSS_RUN_INTEGRATION=1 to run the real HFSS smoke",
        allow_module_level=True,
    )


def test_real_hfss_connect_create_setup_and_attempt_solve(tmp_path: Path) -> None:
    driver = HfssDriver()
    installs = driver.detect_installed()
    assert installs, "expected AEDT/HFSS to be detected before real smoke"

    smoke_dir = Path(os.environ.get("SIM_HFSS_SMOKE_DIR", tmp_path))
    smoke_dir.mkdir(parents=True, exist_ok=True)
    project = smoke_dir / "sim_hfss_smoke.aedt"
    evidence_path = smoke_dir / "sim_hfss_smoke_evidence.json"

    launch = driver.launch(
        ui_mode=os.environ.get("SIM_HFSS_UI_MODE", "no_gui"),
        project=str(project),
        design=os.environ.get("SIM_HFSS_DESIGN", "SimSmoke"),
        solution_type=os.environ.get("SIM_HFSS_SOLUTION_TYPE", "Eigenmode"),
        close_on_exit=True,
    )
    assert launch["ok"], launch

    try:
        assert driver.query("session.summary")["connected"] is True
        assert driver.query("hfss.project.identity")["ok"] is True
        assert driver.query("hfss.design.summary")["ok"] is True

        smoke = driver.run(_SMOKE_SNIPPET, label="real-hfss-smoke")
        assert smoke["ok"], smoke
        evidence = smoke["result"]
        evidence_path.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")

        assert evidence["setup_created"] is True
        require_solve = os.environ.get("SIM_HFSS_REQUIRE_SOLVE", "1").lower()
        if require_solve not in {"0", "false", "no"}:
            assert evidence["solve_ok"] is True, evidence
    finally:
        driver.disconnect()


_SMOKE_SNIPPET = r'''
setup_name = "SimSmokeSetup"
evidence = {
    "project_name": getattr(hfss, "project_name", None),
    "project_file": getattr(hfss, "project_file", None),
    "design_name": getattr(hfss, "design_name", None),
    "solution_type": getattr(hfss, "solution_type", None),
    "aedt_version_id": None,
    "setup_created": False,
    "solve_ok": False,
    "solve_error": None,
}
try:
    evidence["aedt_version_id"] = hfss.aedt_version_id
except Exception as exc:
    evidence["aedt_version_error"] = f"{type(exc).__name__}: {exc}"
try:
    if hasattr(hfss, "modeler") and hasattr(hfss.modeler, "create_box"):
        box = hfss.modeler.create_box(
            [0, 0, 0],
            ["10mm", "10mm", "10mm"],
            name="SimSmokeBox",
            material="vacuum",
        )
        evidence["object"] = getattr(box, "name", str(box))

    setup_names = list(getattr(hfss, "setup_names", []) or [])
    if setup_name not in setup_names:
        setup = hfss.create_setup(setup_name)
        if hasattr(setup, "props"):
            setup.props["MaximumPasses"] = 1
            setup.props["MinimumPasses"] = 1
            setup.props["MinimumConvergedPasses"] = 1
            setup.props["PercentRefinement"] = 10
            setup.update()
    evidence["setup_created"] = setup_name in list(getattr(hfss, "setup_names", []) or [setup_name])

    analyze = getattr(hfss, "analyze_setup", None)
    if callable(analyze):
        evidence["solve_ok"] = bool(analyze(setup_name))
except Exception as exc:
    evidence["solve_error"] = f"{type(exc).__name__}: {exc}"
evidence
'''
