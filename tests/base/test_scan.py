"""Contract tests for read-only historical simulation asset scanning."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from sim.cli import main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _write_abaqus(path: Path, material: str = "Steel") -> None:
    path.write_text(
        "\n".join([
            "*HEADING",
            "*PART, NAME=Bracket",
            "*NODE",
            "1, 0, 0, 0",
            "*ELEMENT, TYPE=C3D8",
            "1, 1, 1, 1, 1, 1, 1, 1, 1",
            f"*MATERIAL, NAME={material}",
            "*ELASTIC",
            "210000, 0.3",
            "*STEP, NAME=Load",
            "*STATIC",
            "*BOUNDARY",
            "1, 1, 3",
            "*END STEP",
        ]),
        encoding="utf-8",
    )


def _json_scan(runner: CliRunner, *args: str):
    result = runner.invoke(main, ["--json", "scan", *args])
    return result, json.loads(result.output)


def test_scan_file_emits_bounded_summary_and_redacts_paths(runner, tmp_path):
    model = tmp_path / "job.inp"
    _write_abaqus(model)

    result, data = _json_scan(runner, str(model))

    assert result.exit_code == 0, result.output
    assert data["schema_version"] == "sim.scan/v1"
    assert data["ok"] is True
    assert data["status"] == "ok"
    assert data["engine"]["name"] == "simparse"
    assert data["request"]["paths"] == ["job.inp"]
    assert data["summary"]["assets"] == 1
    assert data["summary"]["formats"] == {"abaqus-inp": 1}
    assert data["assets"][0]["view"] == "summary"
    assert data["assets"][0]["file_name"] == "job.inp"
    assert "path" not in data["assets"][0]
    assert str(tmp_path) not in result.output


def test_scan_full_and_include_paths_are_explicit_opt_ins(runner, tmp_path):
    model = tmp_path / "job.inp"
    _write_abaqus(model)

    result, data = _json_scan(runner, str(model), "--full", "--include-paths")

    assert result.exit_code == 0, result.output
    asset = data["assets"][0]
    assert "view" not in asset
    assert Path(asset["path"]) == model
    assert data["request"]["view"] == "full"


def test_scan_directory_recursion_can_be_disabled(runner, tmp_path):
    _write_abaqus(tmp_path / "top.inp")
    nested = tmp_path / "nested"
    nested.mkdir()
    _write_abaqus(nested / "nested.inp")

    result, data = _json_scan(runner, str(tmp_path), "--no-recursive")

    assert result.exit_code == 0, result.output
    assert data["summary"]["assets"] == 1
    assert data["assets"][0]["file_name"] == "top.inp"


def test_scan_limit_bounds_returned_assets(runner, tmp_path):
    _write_abaqus(tmp_path / "a.inp")
    _write_abaqus(tmp_path / "b.inp")

    result, data = _json_scan(runner, str(tmp_path), "--limit", "1")

    assert result.exit_code == 0, result.output
    assert data["summary"]["assets"] == 2
    assert data["summary"]["returned"] == 1
    assert data["summary"]["omitted"] == 1
    assert len(data["assets"]) == 1
    assert data["truncated"] is True


def test_scan_mixed_valid_and_missing_roots_is_partial_success(runner, tmp_path):
    model = tmp_path / "job.inp"
    _write_abaqus(model)

    result, data = _json_scan(runner, str(model), str(tmp_path / "missing"))

    assert result.exit_code == 0, result.output
    assert data["ok"] is True
    assert data["status"] == "partial"
    assert data["summary"]["assets"] == 1
    assert data["summary"]["failed"] == 1
    assert data["diagnostics"][0]["error_code"] == "ASSET_PATH_NOT_FOUND"
    assert str(tmp_path) not in result.output


def test_scan_corrupt_asset_does_not_hide_valid_neighbor(runner, tmp_path):
    _write_abaqus(tmp_path / "valid.inp")
    (tmp_path / "corrupt.mph").write_bytes(b"not a zip archive")

    result, data = _json_scan(runner, str(tmp_path))

    assert result.exit_code == 0, result.output
    assert data["ok"] is True
    assert data["status"] == "partial"
    assert data["summary"]["assets"] == 1
    assert data["summary"]["failed"] == 1
    assert data["assets"][0]["file_name"] == "valid.inp"
    assert data["diagnostics"][0]["error_code"] == "ASSET_SCAN_FAILED"


def test_scan_explicit_unsupported_file_uses_stable_error_envelope(runner, tmp_path):
    notes = tmp_path / "notes.txt"
    notes.write_text("not a simulation asset", encoding="utf-8")

    result, data = _json_scan(runner, str(notes))

    assert result.exit_code == 2
    assert data["ok"] is False
    assert data["error_code"] == "ASSET_FORMAT_UNSUPPORTED"
    assert data["details"]["diagnostics"][0]["path"] == "notes.txt"
    assert str(tmp_path) not in result.output


def test_scan_invalid_forced_format_is_a_user_error(runner, tmp_path):
    model = tmp_path / "job.inp"
    _write_abaqus(model)

    result, data = _json_scan(runner, str(model), "--format", "not-a-format")

    assert result.exit_code == 2
    assert data["ok"] is False
    assert data["error_code"] == "ASSET_FORMAT_UNSUPPORTED"


def test_scan_missing_path_is_a_user_error(runner, tmp_path):
    result, data = _json_scan(runner, str(tmp_path / "missing"))

    assert result.exit_code == 2
    assert data["ok"] is False
    assert data["error_code"] == "ASSET_PATH_NOT_FOUND"


def test_scan_rejects_forced_format_for_directory(runner, tmp_path):
    result, data = _json_scan(runner, str(tmp_path), "--format", "abaqus-inp")

    assert result.exit_code == 2
    assert data["ok"] is False
    assert data["error_code"] == "ASSET_FORMAT_UNSUPPORTED"


def test_scan_empty_directory_is_a_valid_empty_result(runner, tmp_path):
    result, data = _json_scan(runner, str(tmp_path))

    assert result.exit_code == 0, result.output
    assert data["ok"] is True
    assert data["summary"]["assets"] == 0
    assert data["diagnostics"] == []


def test_scan_human_output_is_concise(runner, tmp_path):
    model = tmp_path / "job.inp"
    _write_abaqus(model)

    result = runner.invoke(main, ["scan", str(model)])

    assert result.exit_code == 0, result.output
    assert "[sim] scan: 1 asset(s), 0 failure(s), status=ok" in result.output
    assert "abaqus-inp" in result.output
    assert "job.inp" in result.output
    assert str(tmp_path) not in result.output
