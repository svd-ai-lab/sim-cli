"""Tests for retired plugin installer command shims."""
from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from sim import _plugin_install
from sim._plugin_install import InstallReport, bundle_plugins, install_plugin, uninstall_plugin
from sim.cli import main


def test_install_package_spec_returns_exact_uv_replacement():
    report = install_plugin("sim-plugin-comsol")

    assert report.ok is False
    assert report.error_code == "PLUGIN_INSTALL_RETIRED"
    assert "sim plugin install is retired." in report.message
    assert "uv add sim-cli-core sim-plugin-comsol" in report.message


def test_install_short_name_points_to_plugin_index():
    report = install_plugin("comsol")

    assert report.ok is False
    assert report.error_code == "PLUGIN_INSTALL_RETIRED"
    assert "Short solver names are not package specs" in report.message
    assert "docs.svdailab.com/plugin-index" in report.message
    assert "uv add sim-cli-core <plugin-package-spec>" in report.message


def test_installer_module_has_no_pip_invoker():
    assert not hasattr(_plugin_install, "_pip_install")


def test_uninstall_returns_uv_remove_guidance():
    result = uninstall_plugin("comsol")

    assert result["ok"] is False
    assert result["error_code"] == "PLUGIN_INSTALL_RETIRED"
    assert "sim plugin uninstall is retired." in result["message"]
    assert "uv remove sim-plugin-comsol" in result["message"]


def test_bundle_plugins_is_retired(tmp_path: Path):
    result = bundle_plugins(["comsol"], tmp_path / "bundle")

    assert result["ok"] is False
    assert result["fetched"] == []
    assert result["errors"][0]["error_code"] == "PLUGIN_INSTALL_RETIRED"


def test_install_report_dict_includes_all_keys():
    r = InstallReport(
        ok=False,
        name="x",
        source_kind="retired",
        pip_target="...",
        pip_returncode=-1,
        pip_stdout="o",
        pip_stderr="e",
        sync_skills=None,
        error_code="PLUGIN_INSTALL_RETIRED",
        message="m",
    )
    d = r.to_dict()
    for k in (
        "ok", "name", "source_kind", "pip_target", "pip_returncode",
        "pip_stdout", "pip_stderr", "sync_skills", "error_code", "message",
    ):
        assert k in d


def test_cli_plugin_install_human_shows_migration_error():
    runner = CliRunner()
    result = runner.invoke(main, ["plugin", "install", "sim-plugin-comsol"])

    assert result.exit_code == 4
    assert "sim plugin install is retired." in result.output
    assert "uv add sim-cli-core sim-plugin-comsol" in result.output


def test_cli_plugin_install_json_shows_retired_code():
    runner = CliRunner()
    result = runner.invoke(main, ["--json", "plugin", "install", "comsol"])

    assert result.exit_code == 4
    data = json.loads(result.output)
    assert data["ok"] is False
    assert data["error_code"] == "PLUGIN_INSTALL_RETIRED"
    assert "docs.svdailab.com/plugin-index" in data["message"]
