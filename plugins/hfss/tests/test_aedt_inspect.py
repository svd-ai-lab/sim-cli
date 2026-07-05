from __future__ import annotations

import json
import zipfile
from pathlib import Path

from sim_plugin_hfss.aedt_inspect import inspect_aedt, main


AEDT_TEXT = """\
$begin 'AnsoftProject'
ProjectName='PatchProbe'
ProductVersion='2025.2'
$begin 'HFSSModel'
Name='PatchAntenna'
DesignID=0
SolutionType='DrivenModal'
VariableProp('patch_w', 'UD', '', '12mm')
VariableProp('feed_gap', 'UD', '', '0.3mm')
VariableOrders[2: 'patch_w', 'feed_gap']
$begin 'AnalysisSetup'
NAME:Setup1
NAME:Sweep1
RangeStart:='5GHz'
$end 'AnalysisSetup'
$begin 'BoundarySetup'
NAME:Port1
Type:='Lumped Port'
NAME:Radiation
Type:='Radiation'
$end 'BoundarySetup'
ObjectName='Patch'
Material='copper'
$end 'HFSSModel'
$end 'AnsoftProject'
"""


def test_inspect_plain_aedt_extracts_project_hints(tmp_path: Path) -> None:
    project = tmp_path / "patch.aedt"
    project.write_text(AEDT_TEXT, encoding="utf-8")
    results_dir = Path(str(project) + "results") / "PatchAntenna.results"
    results_dir.mkdir(parents=True)
    (results_dir / "F1_SU.txt").write_text("Frequency 5800000000.0\nSuccess 1\n", encoding="utf-8")

    summary = inspect_aedt(project)

    assert summary["ok"] is True
    assert summary["format"] == "aedt"
    assert summary["project"]["name"] == "PatchProbe"
    assert summary["project"]["version_hint"] == "2025.2"
    assert summary["design_count"] == 1
    design = summary["designs"][0]
    assert design["name"] == "PatchAntenna"
    assert design["type"] == "HFSS"
    assert design["solution_type"] == "DrivenModal"
    assert design["variables"]["patch_w"] == "12mm"
    assert design["variables"]["feed_gap"] == "0.3mm"
    assert design["setups"] == ["Setup1"]
    assert design["sweeps"] == ["Sweep1"]
    assert "Port1" in design["excitations"]
    assert "Radiation" in design["boundaries"]
    assert summary["results"]["results_dir"]["exists"] is True
    assert summary["results"]["solution_progress"]["success_count"] == 1
    assert summary["results"]["solution_progress"]["frequencies_ghz"] == [5.8]


def test_inspect_aedtz_zip_extracts_aedt_member(tmp_path: Path) -> None:
    archive = tmp_path / "packed.aedtz"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("docs/readme.txt", "ignore")
        zf.writestr("project/patch.aedt", AEDT_TEXT)

    summary = inspect_aedt(archive)

    assert summary["ok"] is True
    assert summary["format"] == "aedtz_zip"
    assert summary["source"]["aedt_member"] == "project/patch.aedt"
    assert summary["designs"][0]["name"] == "PatchAntenna"


def test_inspect_missing_file_reports_json_error(tmp_path: Path) -> None:
    summary = inspect_aedt(tmp_path / "missing.aedt")

    assert summary["ok"] is False
    assert summary["error_code"] == "FILE_NOT_FOUND"


def test_cli_emits_json(tmp_path: Path, capsys) -> None:
    project = tmp_path / "patch.aedt"
    project.write_text(AEDT_TEXT, encoding="utf-8")

    assert main([str(project), "--compact"]) == 0
    out = capsys.readouterr().out
    summary = json.loads(out)
    assert summary["project"]["name"] == "PatchProbe"
