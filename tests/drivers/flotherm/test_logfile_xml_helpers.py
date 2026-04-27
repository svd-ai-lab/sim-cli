"""Unit tests for Flotherm GUI-log discovery + tailing helpers.

These exercise the install-relative `WinXP/bin/LogFiles/` lookup that
parses each retained `logFile*.xml` GUI session log into structured
:class:`ErrorEntry` records.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from sim.drivers.flotherm._helpers import list_logfile_xmls, tail_logfile_xml


def _write_logfile(path: Path, messages: list[str]) -> None:
    """Write a minimal Flotherm-style GUI session XML at *path*."""
    body = "\n".join(f'  <message text="{m}"/>' for m in messages)
    path.write_text(
        f'<?xml version="1.0"?>\n<log>\n{body}\n</log>\n',
        encoding="utf-8",
    )


def _make_install(root: Path) -> Path:
    """Materialise the `WinXP/bin/LogFiles/` skeleton under *root*."""
    log_dir = root / "WinXP" / "bin" / "LogFiles"
    log_dir.mkdir(parents=True)
    return log_dir


def test_list_logfile_xmls_empty_when_dir_missing(tmp_path: Path) -> None:
    assert list_logfile_xmls(str(tmp_path)) == []


def test_list_logfile_xmls_returns_only_logfile_xmls(tmp_path: Path) -> None:
    log_dir = _make_install(tmp_path)
    _write_logfile(log_dir / "logFile_20260427_120000.xml", ["INFO    I/9001 - x"])
    _write_logfile(log_dir / "logFile_20260427_130000.xml", ["INFO    I/9001 - x"])
    # Non-matching files should be ignored.
    (log_dir / "README.txt").write_text("not a log", encoding="utf-8")
    (log_dir / "other.xml").write_text("<x/>", encoding="utf-8")

    out = list_logfile_xmls(str(tmp_path))
    assert len(out) == 2
    assert all(p.endswith(".xml") and "logFile" in os.path.basename(p) for p in out)


def test_list_logfile_xmls_sorts_newest_first(tmp_path: Path) -> None:
    log_dir = _make_install(tmp_path)
    older = log_dir / "logFile_old.xml"
    newer = log_dir / "logFile_new.xml"
    _write_logfile(older, ["INFO    I/9001 - first"])
    # Force older mtime so the second file is genuinely newer.
    os.utime(older, (time.time() - 60, time.time() - 60))
    _write_logfile(newer, ["INFO    I/9001 - second"])

    out = list_logfile_xmls(str(tmp_path))
    assert out[0] == str(newer)
    assert out[1] == str(older)


def test_tail_logfile_xml_empty_when_no_logs(tmp_path: Path) -> None:
    assert tail_logfile_xml(str(tmp_path)) == []


def test_tail_logfile_xml_default_reads_only_most_recent(tmp_path: Path) -> None:
    log_dir = _make_install(tmp_path)
    older = log_dir / "logFile_old.xml"
    newer = log_dir / "logFile_new.xml"
    _write_logfile(older, ["ERROR   E/11013 - older session lock"])
    os.utime(older, (time.time() - 60, time.time() - 60))
    _write_logfile(newer, ["ERROR   E/15002 - newer session prop fail"])

    out = tail_logfile_xml(str(tmp_path))
    assert isinstance(out, list)
    assert all(isinstance(item, dict) for item in out)
    codes = [item["code"] for item in out]
    assert codes == ["E/15002"]  # only the newer file contributed


def test_tail_logfile_xml_merge_all_returns_newest_first_entries(tmp_path: Path) -> None:
    log_dir = _make_install(tmp_path)
    older = log_dir / "logFile_old.xml"
    newer = log_dir / "logFile_new.xml"
    _write_logfile(older, ["ERROR   E/11013 - older"])
    os.utime(older, (time.time() - 60, time.time() - 60))
    _write_logfile(newer, ["ERROR   E/15002 - newer"])

    out = tail_logfile_xml(str(tmp_path), most_recent_only=False)
    codes = [item["code"] for item in out]
    # Newer file's entries come first; older follows.
    assert codes == ["E/15002", "E/11013"]


def test_tail_logfile_xml_propagates_suggested_action(tmp_path: Path) -> None:
    log_dir = _make_install(tmp_path)
    _write_logfile(
        log_dir / "logFile_x.xml",
        ["ERROR   E/11029 - Failed unknown file type No reader for this file type"],
    )
    out = tail_logfile_xml(str(tmp_path))
    assert len(out) == 1
    assert out[0]["code"] == "E/11029"
    assert "translator.exe" in out[0]["suggested_action"]
