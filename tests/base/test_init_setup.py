"""Tests for ``sim init``, ``sim setup``, ``sim config validate``,
and the ``sim.toml`` schema layer in :mod:`sim.config`.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from sim import config as _cfg
from sim.cli import main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ── sim.toml schema validation ──────────────────────────────────────────────


def test_validate_missing_file(tmp_path: Path):
    errors = _cfg.validate_sim_toml(tmp_path / "no.toml")
    assert errors and "not found" in errors[0]


def test_validate_invalid_toml(tmp_path: Path):
    p = tmp_path / "sim.toml"
    p.write_text("not = valid = toml\n", encoding="utf-8")
    errors = _cfg.validate_sim_toml(p)
    assert errors and "invalid TOML" in errors[0]


def test_validate_missing_sim_table(tmp_path: Path):
    p = tmp_path / "sim.toml"
    p.write_text("[other]\nkey = 1\n", encoding="utf-8")
    errors = _cfg.validate_sim_toml(p)
    assert any("missing [sim] table" in e for e in errors)


def test_validate_minimal_clean(tmp_path: Path):
    p = tmp_path / "sim.toml"
    p.write_text("[sim]\n", encoding="utf-8")
    assert _cfg.validate_sim_toml(p) == []


def test_validate_default_solver_must_be_string(tmp_path: Path):
    p = tmp_path / "sim.toml"
    p.write_text("[sim]\ndefault_solver = 123\n", encoding="utf-8")
    errors = _cfg.validate_sim_toml(p)
    assert any("default_solver must be a string" in e for e in errors)


def test_validate_plugin_entry_requires_name(tmp_path: Path):
    p = tmp_path / "sim.toml"
    p.write_text("[sim]\n[[sim.plugins]]\nversion = '1'\n", encoding="utf-8")
    errors = _cfg.validate_sim_toml(p)
    assert any("missing required 'name'" in e for e in errors)


def test_validate_full_example(tmp_path: Path):
    p = tmp_path / "sim.toml"
    p.write_text("""
[sim]
default_solver = "gmsh"
workspace = "./workspace"
server_port = 7600

[[sim.plugins]]
name = "coolprop"
version = ">=0.1.0"

[[sim.plugins]]
name = "gmsh"
git = "https://github.com/svd-ai-lab/sim-plugin-gmsh"
""".strip(), encoding="utf-8")
    assert _cfg.validate_sim_toml(p) == []


# ── derive_install_source — translate sim.toml → install string ────────────


def test_derive_source_from_wheel():
    s = _cfg.derive_install_source({"name": "x", "wheel": "./x.whl"})
    assert s == "./x.whl"


def test_derive_source_from_git():
    s = _cfg.derive_install_source({"name": "x", "git": "https://example/x"})
    assert s == "git+https://example/x"


def test_derive_source_from_pinned_version():
    s = _cfg.derive_install_source({"name": "x", "version": "==1.2.3"})
    assert s == "x@1.2.3"


def test_derive_source_from_range_falls_back_to_bare_name():
    s = _cfg.derive_install_source({"name": "x", "version": ">=0.1"})
    assert s == "x"


def test_derive_source_bare_name():
    s = _cfg.derive_install_source({"name": "x"})
    assert s == "x"


# ── CLI: sim init / sim config validate / sim setup ─────────────────────────


def test_cli_init_creates_sim_toml(runner: CliRunner, tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = runner.invoke(main, ["init"])
    assert r.exit_code == 0, r.output
    assert (tmp_path / "sim.toml").exists()


def test_cli_init_idempotent(runner: CliRunner, tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "sim.toml").write_text("# my custom\n", encoding="utf-8")
    r = runner.invoke(main, ["init"])
    assert r.exit_code == 0
    # Existing content preserved without --force.
    assert (tmp_path / "sim.toml").read_text(encoding="utf-8") == "# my custom\n"


def test_cli_init_force_regenerates(runner: CliRunner, tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "sim.toml").write_text("# old\n", encoding="utf-8")
    r = runner.invoke(main, ["init", "--force"])
    assert r.exit_code == 0
    body = (tmp_path / "sim.toml").read_text(encoding="utf-8")
    assert "[sim]" in body  # fresh stub


def test_cli_config_validate_ok(runner: CliRunner, tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "sim.toml").write_text("[sim]\n", encoding="utf-8")
    r = runner.invoke(main, ["--json", "config", "validate"])
    assert r.exit_code == 0
    data = json.loads(r.output)
    assert data["ok"] is True


def test_cli_config_validate_fail(runner: CliRunner, tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bad = tmp_path / "sim.toml"
    bad.write_text("[other]\n", encoding="utf-8")
    r = runner.invoke(main, ["--json", "config", "validate", str(bad)])
    assert r.exit_code == 2
    data = json.loads(r.output)
    assert data["ok"] is False
    assert data["errors"]


def test_cli_setup_dry_run_with_no_plugins(runner: CliRunner, tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "sim.toml").write_text("[sim]\n", encoding="utf-8")
    r = runner.invoke(main, ["--json", "setup", "--dry-run"])
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert data["ok"] is True
    assert data["plugins"] == []


def test_cli_setup_missing_sim_toml_errors_cleanly(runner: CliRunner, tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = runner.invoke(main, ["--json", "setup"])
    # Exit 2 = user error per agent-readability.md
    assert r.exit_code == 2
    data = json.loads(r.output)
    assert data["ok"] is False
    assert data["error_code"] == "PLUGIN_NOT_FOUND"


def test_cli_setup_dry_run_lists_what_would_install(runner: CliRunner, tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "sim.toml").write_text("""
[sim]
[[sim.plugins]]
name = "coolprop"
version = "==0.1.0"
""".strip(), encoding="utf-8")
    r = runner.invoke(main, ["--json", "setup", "--dry-run"])
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert data["ok"] is True
    assert len(data["plugins"]) == 1
    assert data["plugins"][0]["name"] == "coolprop"
    assert data["plugins"][0]["source"] == "coolprop@0.1.0"
    assert data["plugins"][0]["action"] == "would-install"
