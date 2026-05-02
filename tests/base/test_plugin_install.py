"""Tests for sim._plugin_install — source resolution and report shape.

These cover the *classification* layer (no real pip calls). The actual
install path is exercised against a fixture wheel in test_plugin_install_e2e
— kept small and skipped when no fixture wheel exists yet.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from sim._plugin_install import (
    InstallReport,
    bundle_plugins,
    install_plugin,
    resolve_source,
)


# ── Source resolution ──────────────────────────────────────────────────────


def test_resolve_local_wheel(tmp_path: Path):
    wheel = tmp_path / "sim_plugin_coolprop-0.1.0-py3-none-any.whl"
    wheel.write_bytes(b"")  # contents irrelevant for resolution
    rs = resolve_source(str(wheel))
    assert rs.kind == "local-wheel"
    assert rs.pip_target == str(wheel.resolve())


def test_resolve_local_sdist(tmp_path: Path):
    sdist = tmp_path / "sim-plugin-coolprop-0.1.0.tar.gz"
    sdist.write_bytes(b"")
    rs = resolve_source(str(sdist))
    assert rs.kind == "local-sdist"


def test_resolve_local_directory(tmp_path: Path):
    pkg_dir = tmp_path / "sim-plugin-foo"
    pkg_dir.mkdir()
    rs = resolve_source(str(pkg_dir))
    assert rs.kind == "local-dir"


def test_resolve_missing_local_path_errors(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        resolve_source(str(tmp_path / "no-such-thing/"))


def test_resolve_git_url():
    url = "git+https://github.com/svd-ai-lab/sim-plugin-ltspice"
    rs = resolve_source(url)
    assert rs.kind == "git-url"
    assert rs.pip_target == url


def test_resolve_wheel_url():
    url = "https://example.com/sim_plugin_ltspice-0.2.3-py3-none-any.whl"
    rs = resolve_source(url)
    assert rs.kind == "wheel-url"
    assert rs.pip_target == url


def test_resolve_sdist_url():
    url = "https://example.com/sim-plugin-x-0.1.0.tar.gz"
    rs = resolve_source(url)
    assert rs.kind == "sdist-url"


def test_resolve_exact_package_spec():
    rs = resolve_source("sim-plugin-ltspice")
    assert rs.kind == "package-spec"
    assert rs.name == "sim-plugin-ltspice"
    assert rs.pip_target == "sim-plugin-ltspice"


def test_resolve_exact_version_package_spec():
    rs = resolve_source("sim-plugin-ltspice==0.2.3")
    assert rs.kind == "package-spec"
    assert rs.name == "sim-plugin-ltspice"
    assert rs.version == "0.2.3"
    assert rs.pip_target == "sim-plugin-ltspice==0.2.3"


def test_resolve_exact_range_package_spec():
    rs = resolve_source("sim-plugin-ltspice>=0.2")
    assert rs.kind == "package-spec"
    assert rs.name == "sim-plugin-ltspice"
    assert rs.version == "0.2"
    assert rs.pip_target == "sim-plugin-ltspice>=0.2"


@pytest.mark.parametrize("name", ["mechanical", "ltspice"])
def test_resolve_bare_short_name_rejected(name: str):
    with pytest.raises(ValueError) as exc:
        resolve_source(name)
    msg = str(exc.value)
    assert "catalog name" in msg
    assert f"sim plugin search {name}" in msg
    assert f"sim-plugin-{name}" in msg


def test_resolve_garbage_raises():
    with pytest.raises(ValueError):
        resolve_source("???not-a-source???")


def test_bundle_plugins_is_disabled_without_index(tmp_path: Path):
    output = tmp_path / "out"
    result = bundle_plugins(["ltspice"], output)
    assert result["ok"] is False
    assert result["fetched"] == []
    assert result["errors"][0]["name"] == "ltspice"
    assert "bundle no longer resolves catalogue names" in result["errors"][0]["error"]


def test_install_bare_short_name_returns_helpful_error(monkeypatch):
    from sim import _plugin_install

    def fail_if_called(*args, **kwargs):
        raise AssertionError("pip install should not be called")

    monkeypatch.setattr(_plugin_install, "_pip_install", fail_if_called)

    report = install_plugin("mechanical")
    assert report.ok is False
    assert report.source_kind == "invalid"
    assert report.error_code == "PLUGIN_NOT_FOUND"
    assert "sim-plugin-mechanical" in report.message


# ── InstallReport shape ─────────────────────────────────────────────────────


def test_install_report_dict_includes_all_keys():
    r = InstallReport(
        ok=True, name="x", source_kind="name", pip_target="...",
        pip_returncode=0, pip_stdout="o", pip_stderr="e",
        sync_skills={"ok": True, "linked": [], "copied": [], "skipped": []},
    )
    d = r.to_dict()
    for k in ("ok", "name", "source_kind", "pip_target",
              "pip_returncode", "pip_stdout", "pip_stderr",
              "sync_skills", "error_code", "message"):
        assert k in d


# ── --python flag plumbing ─────────────────────────────────────────────────


class _FakeProc:
    def __init__(self):
        self.returncode = 0
        self.stdout = ""
        self.stderr = ""


def test_pip_install_pins_python_via_uv(monkeypatch):
    """When uv is on PATH, _pip_install must pass ``--python <exe>``."""
    from sim import _plugin_install

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _FakeProc()

    monkeypatch.setattr(_plugin_install.shutil, "which",
                        lambda exe: "/usr/bin/uv" if exe == "uv" else None)
    monkeypatch.setattr(_plugin_install.subprocess, "run", fake_run)

    _plugin_install._pip_install("sim-plugin-foo", python="/tmp/myvenv/bin/python")

    cmd = captured["cmd"]
    assert cmd[0] == "uv"
    assert "--python" in cmd
    assert "/tmp/myvenv/bin/python" in cmd
    assert cmd[-1] == "sim-plugin-foo"


def test_pip_install_pins_python_via_pip(monkeypatch):
    """When uv is NOT on PATH, _pip_install must invoke ``<exe> -m pip``."""
    from sim import _plugin_install

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _FakeProc()

    monkeypatch.setattr(_plugin_install.shutil, "which", lambda exe: None)
    monkeypatch.setattr(_plugin_install.subprocess, "run", fake_run)

    _plugin_install._pip_install("sim-plugin-foo", python="/tmp/myvenv/bin/python")

    cmd = captured["cmd"]
    assert cmd[0] == "/tmp/myvenv/bin/python"
    assert cmd[1:4] == ["-m", "pip", "install"]


def test_pip_install_defaults_to_sys_executable(monkeypatch):
    """Without an explicit ``python``, fall back to ``sys.executable``."""
    import sys
    from sim import _plugin_install

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _FakeProc()

    monkeypatch.setattr(_plugin_install.shutil, "which",
                        lambda exe: "/usr/bin/uv" if exe == "uv" else None)
    monkeypatch.setattr(_plugin_install.subprocess, "run", fake_run)

    _plugin_install._pip_install("sim-plugin-foo")

    cmd = captured["cmd"]
    assert "--python" in cmd
    assert sys.executable in cmd


def test_install_passes_extra_index_urls(monkeypatch):
    from sim import _plugin_install

    captured = {}

    def fake_pip_install(target, **kwargs):
        captured["target"] = target
        captured["kwargs"] = kwargs
        return _FakeProc()

    monkeypatch.setattr(_plugin_install, "_pip_install", fake_pip_install)
    monkeypatch.setattr(_plugin_install, "_default_skills_target", lambda: Path("/tmp/no-skills"))

    report = install_plugin(
        "sim-plugin-mechanical",
        skip_sync=True,
        extra_index_urls=["https://example.com/simple/"],
    )

    assert report.ok is True
    assert captured["target"] == "sim-plugin-mechanical"
    assert captured["kwargs"]["extra_args"] == [
        "--extra-index-url",
        "https://example.com/simple/",
    ]
