"""CLI contract for offline exports of saved COMSOL MPH data."""

import json
from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from sim.cli import main


@pytest.fixture
def mph(tmp_path):
    path = tmp_path / "model.mph"
    path.write_bytes(b"test MPH")
    return path


@pytest.fixture
def parser(monkeypatch):
    parser = Mock()
    monkeypatch.setattr("sim.assets._load_simparse", lambda: (parser, "0.5.0"))
    return parser


def invoke(*args):
    result = CliRunner().invoke(main, ["--json", "export", *map(str, args)])
    return result, json.loads(result.output)


def test_mesh_forwards_sequence_and_writes_vtu(mph, parser):
    output = mph.with_suffix(".vtu")
    parser.comsol_vtu.side_effect = lambda path, output, sequence: output.write_text("<VTKFile/>")

    result, payload = invoke("mesh", mph, "--sequence", "mesh2", "-o", output)

    assert result.exit_code == 0, result.output
    assert payload == {
        "ok": True, "kind": "mesh", "engine": {"name": "simparse", "version": "0.5.0"},
        "output": str(output),
    }
    assert output.read_text() == "<VTKFile/>"
    parser.comsol_vtu.assert_called_once_with(mph, output, sequence="mesh2")


def test_solution_writes_vector_and_keeps_stdout_bounded(mph, parser):
    output = mph.with_suffix(".json")
    vector = {
        "solution": {"sequence": "sol2", "study_name": "Transient"},
        "solnum": 3, "time_s": 0.1, "real": [1.0, 2.0], "imaginary": [0.25, 0.0],
    }
    parser.comsol_solution.return_value = vector

    result, payload = invoke("solution", mph, "--sequence", "sol2", "--solnum", 3, "-o", output)

    assert result.exit_code == 0, result.output
    assert payload == {
        "ok": True, "kind": "solution", "engine": {"name": "simparse", "version": "0.5.0"},
        "output": str(output), "sequence": "sol2", "solnum": 3, "values": 2, "complex": True,
    }
    assert json.loads(output.read_text()) == vector
    parser.comsol_solution.assert_called_once_with(mph, sequence="sol2", solnum=3)


def test_solution_inventory_does_not_extract_vectors(mph, parser):
    parser.comsol_solutions.return_value = [{"sequence": "sol1", "solution_count": 1}]

    result, payload = invoke("solution", mph, "--list")

    assert result.exit_code == 0, result.output
    assert payload["solutions"] == parser.comsol_solutions.return_value
    parser.comsol_solutions.assert_called_once_with(mph)
    parser.comsol_solution.assert_not_called()


@pytest.mark.parametrize("args", [[], ["--list", "--sequence", "sol1"]])
def test_solution_requires_either_inventory_or_export(mph, parser, args):
    result, payload = invoke("solution", mph, *args)

    assert result.exit_code == 2
    assert payload["error_code"] == "ASSET_EXPORT_FAILED"
    assert not parser.mock_calls


def test_export_refuses_to_overwrite_input(mph, parser):
    alias = mph.with_suffix(".vtu")
    alias.hardlink_to(mph)

    result, payload = invoke("mesh", mph, "-o", alias)

    assert result.exit_code == 2
    assert payload["error_code"] == "ASSET_EXPORT_FAILED"
    assert mph.read_bytes() == b"test MPH"
    parser.comsol_vtu.assert_not_called()


def test_failed_solution_write_preserves_existing_output(mph, parser):
    output = mph.with_suffix(".json")
    output.write_text("existing output")
    parser.comsol_solution.return_value = {"real": [float("nan")]}

    result, payload = invoke("solution", mph, "-o", output)

    assert result.exit_code == 1
    assert payload["error_code"] == "ASSET_EXPORT_FAILED"
    assert output.read_text() == "existing output"
    assert set(mph.parent.iterdir()) == {mph, output}
