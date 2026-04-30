"""Tests for sim._plugin_install — source resolution, bundle, and report shape.

These cover the *classification* layer (no real pip calls) and the bundle
flow against mocked HTTP. The actual install path is exercised against a
fixture wheel in test_plugin_install_e2e — kept small and skipped when
no fixture wheel exists yet.
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest import mock

import pytest

from sim._plugin_install import (
    DEFAULT_INDEX_URL,
    InstallReport,
    bundle_plugins,
    fetch_index,
    index_entry,
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
    url = "git+https://github.com/svd-ai-lab/sim-plugin-coolprop"
    rs = resolve_source(url)
    assert rs.kind == "git-url"
    assert rs.pip_target == url


def test_resolve_wheel_url():
    url = "https://example.com/sim_plugin_x-0.1.0-py3-none-any.whl"
    rs = resolve_source(url)
    assert rs.kind == "wheel-url"


def test_resolve_sdist_url():
    url = "https://example.com/sim-plugin-x-0.1.0.tar.gz"
    rs = resolve_source(url)
    assert rs.kind == "sdist-url"


def test_resolve_bare_name_offline_without_cache_errors(tmp_path: Path, monkeypatch):
    # Force an empty cache dir.
    monkeypatch.setattr("sim._plugin_install._index_cache_dir",
                        lambda: tmp_path / "no-cache")
    with pytest.raises(ValueError):
        resolve_source("coolprop", offline=True)


def test_resolve_bare_name_with_index_uses_wheel_url(tmp_path: Path, monkeypatch):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    cache_idx = cache_dir / "index.json"
    cache_idx.write_text(json.dumps({
        "schema_version": 1,
        "plugins": [{
            "name": "coolprop",
            "git": "https://github.com/svd-ai-lab/sim-plugin-coolprop",
            "license_class": "oss",
            "latest_wheel_url": "https://example.com/x.whl",
        }],
    }), encoding="utf-8")
    monkeypatch.setattr("sim._plugin_install._index_cache_dir", lambda: cache_dir)
    monkeypatch.setattr("sim._plugin_install._index_cache_path",
                        lambda: cache_idx)
    rs = resolve_source("coolprop", offline=True)
    assert rs.kind == "name"
    assert rs.pip_target == "https://example.com/x.whl"


def test_resolve_name_at_version(tmp_path: Path, monkeypatch):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "index.json").write_text(json.dumps({
        "schema_version": 1, "plugins": [],
    }), encoding="utf-8")
    monkeypatch.setattr("sim._plugin_install._index_cache_dir", lambda: cache_dir)
    monkeypatch.setattr("sim._plugin_install._index_cache_path",
                        lambda: cache_dir / "index.json")
    rs = resolve_source("coolprop@0.2.1", offline=False)  # name not in index, falls to optimistic
    assert rs.kind == "name-version"
    assert rs.name == "coolprop"
    assert rs.version == "0.2.1"
    assert "coolprop" in rs.pip_target


def test_resolve_garbage_raises():
    with pytest.raises(ValueError):
        resolve_source("???not-a-source???")


# ── R2 manifest + chained lookup ────────────────────────────────────────────


def _seed_caches(tmp_path: Path, monkeypatch,
                 r2_plugins: dict | None = None,
                 github_plugins: list | None = None):
    """Set up isolated R2 + GitHub cache files and point fetch_index at them."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    r2_cache = cache_dir / "manifest-r2.json"
    github_cache = cache_dir / "index.json"
    r2_cache.write_text(json.dumps({"plugins": r2_plugins or {}}), encoding="utf-8")
    github_cache.write_text(
        json.dumps({"schema_version": 1, "plugins": github_plugins or []}),
        encoding="utf-8",
    )
    monkeypatch.setattr("sim._plugin_install._index_cache_dir", lambda: cache_dir)
    monkeypatch.setattr("sim._plugin_install._index_cache_path", lambda: github_cache)
    monkeypatch.setattr("sim._plugin_install._r2_cache_path", lambda: r2_cache)


def test_r2_lookup_normalizes_to_github_shape(tmp_path: Path, monkeypatch):
    from sim._plugin_install import _r2_lookup
    _seed_caches(tmp_path, monkeypatch, r2_plugins={
        "comsol": {"version": "0.1.0",
                    "wheel": "https://cdn.svdailab.com/wheels/comsol.whl"},
    })
    e = _r2_lookup("comsol", offline=True)
    assert e is not None
    assert e["name"] == "comsol"
    assert e["latest_version"] == "0.1.0"
    assert e["latest_wheel_url"] == "https://cdn.svdailab.com/wheels/comsol.whl"

    assert _r2_lookup("absent", offline=True) is None


def test_r2_lookup_skips_entry_without_wheel(tmp_path: Path, monkeypatch):
    """A malformed R2 entry (no wheel) must miss so we fall back."""
    from sim._plugin_install import _r2_lookup
    _seed_caches(tmp_path, monkeypatch, r2_plugins={
        "comsol": {"version": "0.1.0"},  # missing wheel
    })
    assert _r2_lookup("comsol", offline=True) is None


def test_index_entry_chained_prefers_r2(tmp_path: Path, monkeypatch):
    from sim._plugin_install import index_entry_chained
    _seed_caches(
        tmp_path, monkeypatch,
        r2_plugins={"ltspice": {"version": "0.2.1",
                                  "wheel": "https://r2.example/ltspice.whl"}},
        github_plugins=[{"name": "ltspice", "license_class": "oss",
                          "latest_wheel_url": "https://gh.example/ltspice.whl"}],
    )
    e = index_entry_chained("ltspice", offline=True)
    assert e["latest_wheel_url"] == "https://r2.example/ltspice.whl"


def test_index_entry_chained_falls_back_to_github(tmp_path: Path, monkeypatch):
    from sim._plugin_install import index_entry_chained
    _seed_caches(
        tmp_path, monkeypatch,
        r2_plugins={},
        github_plugins=[{"name": "pybamm", "license_class": "oss",
                          "latest_wheel_url": "https://gh.example/pybamm.whl"}],
    )
    e = index_entry_chained("pybamm", offline=True)
    assert e is not None
    assert e["latest_wheel_url"] == "https://gh.example/pybamm.whl"


def test_index_entry_chained_returns_none_when_neither_has_it(tmp_path: Path, monkeypatch):
    from sim._plugin_install import index_entry_chained
    _seed_caches(tmp_path, monkeypatch)
    assert index_entry_chained("nope", offline=True) is None


def test_resolve_bare_name_uses_r2_wheel(tmp_path: Path, monkeypatch):
    """Default chain lookup: R2 hit wins."""
    _seed_caches(
        tmp_path, monkeypatch,
        r2_plugins={"comsol": {"version": "0.1.0",
                                 "wheel": "https://r2.example/comsol.whl"}},
        github_plugins=[],
    )
    rs = resolve_source("comsol", offline=True)
    assert rs.kind == "name"
    assert rs.pip_target == "https://r2.example/comsol.whl"


def test_resolve_bare_name_falls_back_to_github(tmp_path: Path, monkeypatch):
    """Default chain lookup: R2 miss → GitHub wheel URL."""
    _seed_caches(
        tmp_path, monkeypatch,
        r2_plugins={},
        github_plugins=[{"name": "pybamm", "license_class": "oss",
                          "latest_wheel_url": "https://gh.example/pybamm.whl"}],
    )
    rs = resolve_source("pybamm", offline=True)
    assert rs.kind == "name"
    assert rs.pip_target == "https://gh.example/pybamm.whl"


def test_resolve_explicit_index_url_skips_chain(tmp_path: Path, monkeypatch):
    """Explicit index_url uses just that source — no R2 fallback."""
    _seed_caches(
        tmp_path, monkeypatch,
        r2_plugins={"comsol": {"version": "0.1.0",
                                 "wheel": "https://r2.example/comsol.whl"}},
        github_plugins=[{"name": "comsol", "license_class": "oss",
                          "latest_wheel_url": "https://gh.example/comsol.whl"}],
    )
    from sim._plugin_install import DEFAULT_INDEX_URL
    rs = resolve_source("comsol", offline=True, index_url=DEFAULT_INDEX_URL)
    assert rs.pip_target == "https://gh.example/comsol.whl"


# ── Index fetch + cache ──────────────────────────────────────────────────────


def test_fetch_index_offline_missing_cache_returns_empty(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sim._plugin_install._index_cache_dir",
                        lambda: tmp_path / "missing")
    monkeypatch.setattr("sim._plugin_install._index_cache_path",
                        lambda: tmp_path / "missing" / "index.json")
    idx = fetch_index(offline=True)
    assert idx == {"schema_version": 1, "plugins": []}


def test_index_entry_lookup(tmp_path: Path, monkeypatch):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "index.json").write_text(json.dumps({
        "schema_version": 1,
        "plugins": [
            {"name": "coolprop", "license_class": "oss"},
            {"name": "simpy", "license_class": "oss"},
        ],
    }), encoding="utf-8")
    monkeypatch.setattr("sim._plugin_install._index_cache_dir", lambda: cache_dir)
    monkeypatch.setattr("sim._plugin_install._index_cache_path",
                        lambda: cache_dir / "index.json")
    e = index_entry("coolprop", offline=True)
    assert e is not None and e["name"] == "coolprop"
    assert index_entry("nope", offline=True) is None


# ── Bundle ──────────────────────────────────────────────────────────────────


def test_bundle_plugins_writes_filtered_index(tmp_path: Path, monkeypatch):
    """Bundle should write an index.json with only the requested plugins."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setattr("sim._plugin_install._index_cache_dir", lambda: cache_dir)
    monkeypatch.setattr("sim._plugin_install._index_cache_path",
                        lambda: cache_dir / "index.json")

    full_index = {
        "schema_version": 1,
        "plugins": [
            {"name": "coolprop",
             "latest_wheel_url": "http://fake/coolprop.whl",
             "license_class": "oss"},
            {"name": "simpy",
             "latest_wheel_url": "http://fake/simpy.whl",
             "license_class": "oss"},
        ],
    }
    (cache_dir / "index.json").write_text(json.dumps(full_index), encoding="utf-8")

    # Real file-like; bundle uses shutil.copyfileobj which calls .read(size).
    import io

    class _FakeResp(io.BytesIO):
        def __enter__(self):
            return self
        def __exit__(self, *a):
            self.close()

    def fake_open(url, timeout=30):
        return _FakeResp(b"WHEEL")

    output = tmp_path / "out"
    with mock.patch("sim._plugin_install.urllib.request.urlopen", fake_open):
        result = bundle_plugins(["coolprop"], output)

    assert result["ok"] is True
    assert result["fetched"] == ["coolprop"]
    written_idx = json.loads((output / "index.json").read_text(encoding="utf-8"))
    assert len(written_idx["plugins"]) == 1
    assert written_idx["plugins"][0]["name"] == "coolprop"
    assert written_idx["plugins"][0]["latest_wheel_url"].startswith("file://")


def test_bundle_plugins_unknown_returns_partial_failure(tmp_path: Path, monkeypatch):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "index.json").write_text(json.dumps({"plugins": []}), encoding="utf-8")
    monkeypatch.setattr("sim._plugin_install._index_cache_dir", lambda: cache_dir)
    monkeypatch.setattr("sim._plugin_install._index_cache_path",
                        lambda: cache_dir / "index.json")

    output = tmp_path / "out"
    result = bundle_plugins(["nope"], output)
    assert result["ok"] is False
    assert result["fetched"] == []
    assert result["errors"][0]["name"] == "nope"


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
