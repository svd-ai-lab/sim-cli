"""Tests for ``sim plugin`` commands and the underlying discovery layer.

Post-Phase-3b ``_BUILTIN_REGISTRY`` is empty. The conftest synthetic
``coolprop`` driver (autouse fixture, ``tests/base/`` only) is what makes
these tests find anything at all — when it's active, plugin/list/doctor
see a single registered driver named "coolprop". Tests for actually
installing external plugins (`sim plugin install <wheel>`) live in
test_plugin_install.py.
"""
from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from sim import plugins as _plugins
from sim.cli import main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ── Discovery layer ─────────────────────────────────────────────────────────


def test_list_installed_plugins_returns_synthetic_coolprop():
    rows = _plugins.list_installed_plugins()
    assert rows, "synthetic coolprop should be visible via the conftest fixture"
    names = {r.name for r in rows}
    assert "coolprop" in names, f"missing synthetic driver: {sorted(names)}"


def test_synthetic_row_marked_builtin_true():
    rows = _plugins.list_installed_plugins()
    coolprop = next((r for r in rows if r.name == "coolprop"), None)
    assert coolprop is not None
    # Conftest injects the synthetic into _BUILTIN_REGISTRY for the duration
    # of each tests/base/ test, so it appears as a builtin.
    assert coolprop.builtin is True


def test_plugin_info_for_unknown_returns_none():
    assert _plugins.plugin_info_for("no-such-plugin") is None


def test_skills_dir_for_unknown_returns_none():
    assert _plugins.skills_dir_for("no-such-plugin") is None


# ── Doctor ──────────────────────────────────────────────────────────────────


def test_doctor_unknown_plugin_returns_failed_report():
    report = _plugins.doctor("no-such-plugin")
    assert report.ok is False
    assert report.fail_count >= 1
    assert any(c.label == "registered" and c.status == "fail" for c in report.checks)


def test_doctor_built_in_passes_at_least_registration():
    report = _plugins.doctor("coolprop")
    assert any(c.label == "registered" and c.status == "ok" for c in report.checks)
    assert any(c.label == "driver_imports" and c.status == "ok" for c in report.checks)


def test_doctor_all_runs_against_every_plugin():
    reports = _plugins.doctor_all()
    assert len(reports) == len(_plugins.list_installed_plugins())


# ── CLI ─────────────────────────────────────────────────────────────────────


def test_cli_plugin_list_human_output(runner):
    r = runner.invoke(main, ["plugin", "list"])
    assert r.exit_code == 0, r.output
    assert "plugin(s) registered" in r.output


def test_cli_plugin_list_json(runner):
    r = runner.invoke(main, ["--json", "plugin", "list"])
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert isinstance(data, list)
    assert any(row["name"] == "coolprop" for row in data)
    for row in data:
        # to_dict shape contract
        for k in ("name", "package", "version", "builtin", "has_skills", "driver_module"):
            assert k in row, f"missing key {k} in {row}"


def test_cli_plugin_info_unknown(runner):
    r = runner.invoke(main, ["--json", "plugin", "info", "no-such-thing"])
    assert r.exit_code == 2
    data = json.loads(r.output)
    assert data["ok"] is False
    assert data["error_code"] == "PLUGIN_NOT_FOUND"


def test_cli_plugin_info_known_built_in(runner):
    r = runner.invoke(main, ["--json", "plugin", "info", "coolprop"])
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert data["ok"] is True
    assert data["plugin"]["name"] == "coolprop"
    assert data["plugin"]["builtin"] is True


def test_cli_plugin_doctor_specific_built_in(runner):
    r = runner.invoke(main, ["--json", "plugin", "doctor", "coolprop"])
    # Exit code is the fail count; built-ins should all pass.
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert data["ok"] is True
    assert data["fail_count"] == 0


def test_cli_plugin_doctor_all_built_ins(runner):
    r = runner.invoke(main, ["--json", "plugin", "doctor", "--all"])
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert data["ok"] is True
    # Post-Phase-3b _BUILTIN_REGISTRY is empty; only the conftest synthetic
    # coolprop driver is registered for tests/base/ scope.
    assert len(data["reports"]) >= 1


def test_cli_plugin_doctor_unknown_fails(runner):
    r = runner.invoke(main, ["--json", "plugin", "doctor", "no-such-plugin"])
    # One fail: the registered check.
    assert r.exit_code == 1
    data = json.loads(r.output)
    assert data["fail_count"] >= 1


def test_cli_plugin_doctor_no_args_returns_error(runner):
    r = runner.invoke(main, ["--json", "plugin", "doctor"])
    assert r.exit_code == 2
    data = json.loads(r.output)
    assert data["ok"] is False
    assert data["error_code"] == "PLUGIN_NOT_FOUND"


# ── Sync skills ─────────────────────────────────────────────────────────────


def test_sync_skills_creates_target_dir_and_returns_dict(tmp_path):
    target = tmp_path / "skills"
    out = _plugins.sync_skills_to(target, copy=True)
    assert out["ok"] is True
    assert target.exists()
    # Built-ins don't ship sim.skills entry-points, so all are skipped.
    assert isinstance(out["skipped"], list)
    assert isinstance(out["linked"], list)
    assert isinstance(out["copied"], list)
