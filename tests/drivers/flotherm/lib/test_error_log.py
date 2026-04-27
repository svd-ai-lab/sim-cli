"""Unit tests for the structured `floerror.log` parser."""
from __future__ import annotations

from pathlib import Path

from sim.drivers.flotherm.lib.error_log import (
    CODE_CATALOGUE,
    FATAL_CODES,
    ErrorEntry,
    parse_error_line,
    parse_error_log,
    parse_error_log_text,
    parse_logfile_xml,
    read_floerror_log,
)


# --- parse_error_line ------------------------------------------------------

def test_parse_error_line_property_not_found() -> None:
    line = "ERROR   E/15002 - Command failed to find property: power"
    e = parse_error_line(line)
    assert e is not None
    assert e.code == "E/15002"
    assert e.severity == "error"
    assert "find property" in e.message
    assert e.suggested_action  # non-empty — it's catalogued
    assert e.raw == line


def test_parse_error_line_warning() -> None:
    e = parse_error_line("WARN    W/15000 - Aborting XML due to previous error")
    assert e is not None
    assert e.code == "W/15000"
    assert e.severity == "warning"


def test_parse_error_line_info_solver_converged() -> None:
    e = parse_error_line("INFO    I/9001 - Solver stopped: steady solution converged")
    assert e is not None
    assert e.code == "I/9001"
    assert e.severity == "info"
    assert "converged" in e.suggested_action


def test_parse_error_line_unknown_code_no_action() -> None:
    e = parse_error_line("ERROR   E/99999 - Made-up code we do not catalogue")
    assert e is not None
    assert e.code == "E/99999"
    assert e.severity == "error"
    assert e.suggested_action == ""  # unknown codes still parse, just no action


def test_parse_error_line_blank_returns_none() -> None:
    assert parse_error_line("") is None
    assert parse_error_line("   \n") is None


def test_parse_error_line_no_code_returns_none() -> None:
    assert parse_error_line("plain log line with no severity code") is None


# --- parse_error_log_text -------------------------------------------------

_FIXTURE = """
INFO    I/9033 - Total number of Grid Cells are: 1
ERROR   E/9012 - Too few grid-cells to be solved NX = 1 and NY = 1
ERROR   E/11029 - Failed unknown file type No reader for this file type - C:\\foo
WARN    W/15000 - Aborting XML due to previous error
random unparseable line that should be skipped
""".strip()


def test_parse_error_log_text_picks_up_all_codes() -> None:
    entries = parse_error_log_text(_FIXTURE)
    codes = [e.code for e in entries]
    assert codes == ["I/9033", "E/9012", "E/11029", "W/15000"]


def test_parse_error_log_text_skips_blank_and_unparseable_lines() -> None:
    entries = parse_error_log_text(_FIXTURE)
    # 4 codes from 5 candidate lines (the random one is skipped).
    assert len(entries) == 4
    assert all(isinstance(e, ErrorEntry) for e in entries)


# --- parse_error_log (workspace path) -------------------------------------

def test_parse_error_log_reads_workspace_file(tmp_path: Path) -> None:
    (tmp_path / "floerror.log").write_text(_FIXTURE, encoding="utf-8")
    out = parse_error_log(str(tmp_path))
    assert isinstance(out, list)
    assert all(isinstance(item, dict) for item in out)
    codes = [item["code"] for item in out]
    assert "E/11029" in codes
    # Catalogued action is propagated.
    e11029 = next(item for item in out if item["code"] == "E/11029")
    assert "translator.exe" in e11029["suggested_action"]


def test_parse_error_log_missing_file_returns_empty(tmp_path: Path) -> None:
    assert parse_error_log(str(tmp_path)) == []


# --- read_floerror_log backward compat -----------------------------------

def test_read_floerror_log_returns_legacy_tuple(tmp_path: Path) -> None:
    log = (
        "registerStart runTable exception: invalid map<K, T> key\n"
        "ERROR   E/11029 - Failed unknown file type\n"
        "ERROR   E/9012 - Too few grid-cells to be solved\n"
    )
    (tmp_path / "floerror.log").write_text(log, encoding="utf-8")
    content, fatals, warns = read_floerror_log(str(tmp_path))
    assert content == log
    assert any("E/11029" in f for f in fatals)
    assert any("E/9012" in f for f in fatals)
    assert any("runTable" in w for w in warns)


def test_read_floerror_log_missing_file_returns_empty(tmp_path: Path) -> None:
    assert read_floerror_log(str(tmp_path)) == ("", [], [])


# --- parse_logfile_xml ----------------------------------------------------

def test_parse_logfile_xml_extracts_messages(tmp_path: Path) -> None:
    xml = """<?xml version="1.0"?>
<log>
  <message text="ERROR   E/15002 - Command failed to find property: foo"/>
  <message text="WARN    W/15000 - Aborting XML due to previous error"/>
  <message text="non-coded message ignored"/>
</log>
"""
    p = tmp_path / "logFile_2026.xml"
    p.write_text(xml, encoding="utf-8")
    out = parse_logfile_xml(str(p))
    assert [e.code for e in out] == ["E/15002", "W/15000"]


def test_parse_logfile_xml_missing_file_returns_empty(tmp_path: Path) -> None:
    assert parse_logfile_xml(str(tmp_path / "nonexistent.xml")) == []


def test_parse_logfile_xml_malformed_xml_returns_empty(tmp_path: Path) -> None:
    p = tmp_path / "bad.xml"
    p.write_text("<not></balanced>", encoding="utf-8")
    assert parse_logfile_xml(str(p)) == []


# --- catalogue invariants -------------------------------------------------

def test_fatal_codes_are_in_catalogue() -> None:
    """Every FATAL_CODES entry should have a catalogued suggested_action."""
    for code in FATAL_CODES:
        assert code in CODE_CATALOGUE, f"{code} listed as fatal but no action"
        assert CODE_CATALOGUE[code], f"{code} has empty action"


def test_catalogue_codes_are_well_formed() -> None:
    for code in CODE_CATALOGUE:
        prefix, _, digits = code.partition("/")
        assert prefix in {"E", "W", "I"}
        assert digits.isdigit()
