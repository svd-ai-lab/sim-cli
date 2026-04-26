"""pack.py — read-only .pack inspection helpers."""
from __future__ import annotations

import zipfile
from pathlib import Path

from sim.drivers.flotherm.lib.pack import (
    lint_pack,
    pack_project_dir,
    pack_project_name,
)


def _make_pack(path: Path, project_dir_name: str) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(f"{project_dir_name}/marker", "ok")
    return path


def test_pack_project_name_strips_guid():
    assert pack_project_name("Mobile_Demo.AE152DF44810B5C369D") == "Mobile_Demo"
    assert pack_project_name("NoGuid") == "NoGuid"


def test_pack_project_dir_reads_top_level(tmp_path: Path):
    p = _make_pack(tmp_path / "demo.pack", "MyProject.GUID00")
    assert pack_project_dir(p) == "MyProject.GUID00"


def test_pack_project_dir_returns_none_for_garbage(tmp_path: Path):
    p = tmp_path / "bad.pack"
    p.write_bytes(b"not a zip")
    assert pack_project_dir(p) is None


def test_lint_pack_ok(tmp_path: Path):
    p = _make_pack(tmp_path / "good.pack", "Proj.GUID")
    r = lint_pack(p)
    assert r.ok is True


def test_lint_pack_empty_file(tmp_path: Path):
    p = tmp_path / "empty.pack"
    p.write_bytes(b"")
    r = lint_pack(p)
    assert r.ok is False
    assert any("empty" in d.message.lower() for d in r.diagnostics)


def test_lint_pack_bad_zip(tmp_path: Path):
    p = tmp_path / "bad.pack"
    p.write_bytes(b"\x00not a zip\x00\x00")
    r = lint_pack(p)
    assert r.ok is False
    assert any("zip" in d.message.lower() for d in r.diagnostics)
