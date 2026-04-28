"""Tests for tools/lint-public-corpus.py.

Smoke-only: the script's core matching logic (pattern building, allow-comment
detection, whitelist application) is what we exercise. We don't assert on
the full repo report — that's an inventory that changes over time.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "tools" / "lint-public-corpus.py"


@pytest.fixture
def lint_module():
    spec = importlib.util.spec_from_file_location("lint_public_corpus", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    # Register in sys.modules before exec so the @dataclass decorator can
    # resolve forward refs via cls.__module__ lookup.
    sys.modules["lint_public_corpus"] = mod
    try:
        spec.loader.exec_module(mod)
        yield mod
    finally:
        sys.modules.pop("lint_public_corpus", None)


def test_pattern_matches_word_boundary(lint_module):
    pat = lint_module._build_pattern()
    assert pat.search("we use Fluent here")
    assert pat.search("Fluent.")
    # word-boundary: shouldn't match inside larger identifiers
    assert not pat.search("influencer")
    assert not pat.search("affluent")
    assert not pat.search("antifluentish")


def test_pattern_case_insensitive(lint_module):
    pat = lint_module._build_pattern()
    for s in ["fluent", "FLUENT", "Fluent", "fLuEnT"]:
        assert pat.search(s), f"failed to match {s!r}"


def test_pattern_alternation_covers_multiword_tokens(lint_module):
    pat = lint_module._build_pattern()
    # ls-dyna and ls_dyna both flagged — they're hyphenated tokens
    m = pat.search("we ran ls-dyna on this")
    assert m and m.group(1).lower() == "ls-dyna"
    m = pat.search("ls_dyna deck")
    assert m and m.group(1).lower() == "ls_dyna"


def test_token_whitelist_marks_as_allowed(lint_module, tmp_path):
    f = tmp_path / "x.py"
    f.write_text("# we use ltspice for circuit sims\n")
    pat = lint_module._build_pattern()
    hits = lint_module.scan_file(f, pat)
    assert len(hits) == 1
    assert hits[0].token == "ltspice"
    assert hits[0].whitelisted is True
    assert hits[0].whitelist_reason == "TOKEN_WHITELIST"


def test_allow_comment_marks_as_allowed_with_reason(lint_module, tmp_path):
    f = tmp_path / "x.py"
    f.write_text("vendor = 'ANSYS'  # allow-vendor-name: env var name is fixed\n")
    pat = lint_module._build_pattern()
    hits = lint_module.scan_file(f, pat)
    assert len(hits) == 1
    assert hits[0].token == "ansys"
    assert hits[0].whitelisted is True
    assert "env var name" in hits[0].whitelist_reason


def test_no_allow_comment_means_flagged(lint_module, tmp_path):
    f = tmp_path / "x.py"
    f.write_text("# we ran fluent here\n")
    pat = lint_module._build_pattern()
    hits = lint_module.scan_file(f, pat)
    assert len(hits) == 1
    assert hits[0].whitelisted is False


def test_warn_mode_exits_zero_with_flagged_hits(tmp_path):
    # Create a tiny git repo with one offending file.
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "x.py").write_text("# uses fluent\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)

    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0
    assert "flagged" in proc.stdout.lower()


def test_fail_mode_exits_one_with_flagged_hits(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "x.py").write_text("# uses fluent\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)

    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(tmp_path), "--fail"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 1


def test_fail_mode_exits_zero_when_clean(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "x.py").write_text("# nothing to see\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)

    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(tmp_path), "--fail"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0
    assert "clean" in proc.stdout.lower()


def test_json_output_parses(tmp_path):
    import json
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "x.py").write_text("# uses fluent\n# uses ltspice\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)

    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(tmp_path), "--json"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["total"] == 2
    assert data["flagged"] == 1
    assert data["allowed"] == 1
    assert data["ok"] is False
