"""Tests for the ``sim describe`` command and its underlying manifest builder.

These tests are the contract for agents: if any of them fail, an agent's
discovery flow breaks. Run them with ``pytest tests/base/test_describe.py``.
"""
from __future__ import annotations

import json

import click
import pytest
from click.testing import CliRunner

from sim import describe as _describe
from sim.cli import main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ── Manifest shape ──────────────────────────────────────────────────────────


def test_manifest_has_required_top_level_keys():
    m = _describe.build_manifest(main, version="x.y.z")
    assert m["schema_version"] == _describe.SCHEMA_VERSION
    assert m["version"] == "x.y.z"
    assert isinstance(m["commands"], list) and m["commands"]
    assert "schemas" in m and "error_codes" in m


def test_manifest_includes_every_top_level_command():
    m = _describe.build_manifest(main, version="0")
    names = {c["name"] for c in m["commands"]}
    # Spot-check a representative subset of expected commands
    for required in ("run", "lint", "connect", "exec", "ps", "describe", "config"):
        assert required in names, f"missing command: {required}"


def test_manifest_includes_nested_config_subcommands():
    m = _describe.build_manifest(main, version="0")
    names = {c["name"] for c in m["commands"]}
    for required in ("config show", "config path", "config init"):
        assert required in names


def test_every_command_has_summary_and_help():
    m = _describe.build_manifest(main, version="0")
    for cmd in m["commands"]:
        # Summary may be derived from docstring; never None.
        assert isinstance(cmd.get("summary", ""), str)
        assert isinstance(cmd.get("help", ""), str)


def test_every_command_has_examples_or_is_a_pure_group():
    """Examples are required for leaf commands; groups are exempt."""
    m = _describe.build_manifest(main, version="0")
    leaf_commands_missing_examples: list[str] = []
    for cmd in m["commands"]:
        # Skip pure groups (config) — their leaves carry the examples.
        if cmd["name"] in {"config"}:
            continue
        if not cmd["examples"]:
            leaf_commands_missing_examples.append(cmd["name"])
    assert not leaf_commands_missing_examples, (
        f"Commands without examples: {leaf_commands_missing_examples}. "
        f"Add an entry to _EXAMPLES in src/sim/describe.py."
    )


# ── Error codes ─────────────────────────────────────────────────────────────


def test_error_code_enum_is_closed_and_documented():
    """Every code has a description; no empty values."""
    for code, desc in _describe.ERROR_CODES.items():
        assert code.isupper(), f"error code must be SCREAMING_SNAKE: {code!r}"
        assert desc and isinstance(desc, str), f"missing description for {code}"


def test_error_codes_in_manifest_match_module_dict():
    m = _describe.build_manifest(main, version="0")
    manifest_codes = {entry["code"] for entry in m["error_codes"]}
    assert manifest_codes == set(_describe.ERROR_CODES.keys())


# ── Schemas ─────────────────────────────────────────────────────────────────


def test_schemas_have_required_types():
    """Every schema exposes a 'type' key (or const for the error envelope)."""
    for name, schema in _describe.SCHEMAS.items():
        assert isinstance(schema, dict), f"{name} must be dict"
        assert "type" in schema, f"{name} missing 'type' key"


def test_error_envelope_schema_references_full_error_enum():
    env = _describe.SCHEMAS["ErrorEnvelope"]
    enum = env["properties"]["error_code"]["enum"]
    assert set(enum) == set(_describe.ERROR_CODES.keys())


# ── CLI invocation ──────────────────────────────────────────────────────────


def test_describe_full_manifest_outputs_valid_json(runner):
    result = runner.invoke(main, ["describe"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["schema_version"] == 1
    assert data["commands"]


def test_describe_one_command(runner):
    result = runner.invoke(main, ["describe", "run"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["name"] == "run"
    assert data["examples"]


def test_describe_unknown_command_returns_error_envelope(runner):
    result = runner.invoke(main, ["describe", "no-such-command"])
    assert result.exit_code == 2
    data = json.loads(result.output)
    assert data["ok"] is False
    assert data["error_code"] == "PLUGIN_NOT_FOUND"
    assert "no-such-command" in data["message"]


def test_describe_schema_by_name(runner):
    result = runner.invoke(main, ["describe", "--schema", "RunResult"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["type"] == "object"
    assert "ok" in data["properties"]


def test_describe_unknown_schema_returns_error(runner):
    result = runner.invoke(main, ["describe", "--schema", "Nope"])
    assert result.exit_code == 2
    data = json.loads(result.output)
    assert data["ok"] is False


def test_describe_error_codes_only(runner):
    result = runner.invoke(main, ["describe", "--error-codes"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert all("code" in e and "description" in e for e in data)
    codes = {e["code"] for e in data}
    assert "RUN_FAILED" in codes
    assert "PROTOCOL_VIOLATION" in codes


def test_describe_dotted_path(runner):
    """`sim describe config.show` should resolve like `sim describe 'config show'`."""
    r1 = runner.invoke(main, ["describe", "config show"])
    r2 = runner.invoke(main, ["describe", "config.show"])
    assert r1.exit_code == 0
    assert r2.exit_code == 0
    d1 = json.loads(r1.output)
    d2 = json.loads(r2.output)
    # Names will differ (one uses space, one dot), but the underlying data should match.
    d1.pop("name", None)
    d2.pop("name", None)
    assert d1 == d2
