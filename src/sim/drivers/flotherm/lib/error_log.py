"""`floerror.log` and `WinXP\\bin\\LogFiles\\logFile*.xml` parsing.

The error code catalogue (E/6xxx, E/9xxx, E/11xxx, E/15xxx and friends) is
documented in
`sim-skills/flotherm/base/reference/error_codes.md` — that doc is the
authoritative source for the severity / message / driver-action columns
encoded in :data:`CODE_CATALOGUE` below. Provenance: Flotherm 2504.
"""
from __future__ import annotations

import os
import re
from contextlib import suppress
from dataclasses import asdict, dataclass

# Line shape: "ERROR   E/15002 - Command failed to find property: foo".
# Severity prefix has variable whitespace; strip before matching.
_LINE_RE = re.compile(r"\b([EWI])/(\d+)\s*-?\s*(.*)")
_SEVERITY = {"E": "error", "W": "warning", "I": "info"}


@dataclass(frozen=True)
class ErrorEntry:
    """One parsed diagnostic line."""

    code: str               # "E/15002"
    severity: str           # "error" | "warning" | "info"
    message: str            # remainder of the line after the code
    suggested_action: str   # short driver-side recommendation; "" if unknown
    raw: str                # original line, stripped


# Code → suggested driver action. Sourced from
# sim-skills/flotherm/base/reference/error_codes.md (Flotherm 2504).
# Codes not listed here parse as ErrorEntry with suggested_action="".
CODE_CATALOGUE: dict[str, str] = {
    # Table / CSV export
    "E/6000": "Surface to caller; do not retry without changing inputs.",
    # Mesher / grid
    "E/9012": "Treat as fatal; correlate with preceding E/11029. Don't retry without a successful translator pass.",
    "I/9001": "Solver converged — positive signal.",
    "I/9033": "Pre-flight grid count; value of 1 is diagnostic of E/9012.",
    # Project lifecycle
    "E/11008": "Validate import_type ∈ {'Pack File','FloXML','PDML',…} before re-emit.",
    "E/11013": "Run <project_unlock project_name=…/> first, retry <project_load>. If repeated, fall back to flounlock.exe -d <project>.",
    "E/11029": "Don't go through flotherm.bat -b; use direct translator.exe + solexe.exe. Treat as fatal.",
    "E/15105": "If preceded by E/11013, retry after <project_unlock>. Otherwise fatal — verify project dir and PDProject/group.",
    # FloSCRIPT runtime
    "E/15000": "Surface; do not retry. Caller can verify with <find> + <commonStringQueryConstraint>.",
    "E/15001": "Surface; do not retry. Workaround: build attributes by hand (see ISSUE-006).",
    "E/15002": "Surface; do not retry. Always pair with the immediately following W/15000. Suggest the recording-oracle workflow.",
    "E/15013": "Driver bug — should have been caught by lib.floscript._validate_xsd before dispatch.",
    "W/15000": "Companion warning that always follows a fatal E/15xxx.",
}

# Codes that should flip the job state to failed when freshly observed.
FATAL_CODES: frozenset[str] = frozenset({
    "E/6000",
    "E/9012",
    "E/11008",
    "E/11013",
    "E/11029",
    "E/15000",
    "E/15001",
    "E/15002",
    "E/15013",
    "E/15105",
})

# Legacy non-coded patterns kept for the floserv RunTable bug.
_LEGACY_WARNING_PATTERNS = ("registerStart runTable exception",)


def parse_error_line(line: str) -> ErrorEntry | None:
    """Extract one :class:`ErrorEntry` from a single log line.

    Returns ``None`` if the line carries no recognised severity-coded token.
    """
    text = line.strip()
    if not text:
        return None
    for token in text.split():
        m = _LINE_RE.match(token)
        if not m:
            continue
        sev_prefix, code_digits, _ = m.groups()
        code = f"{sev_prefix}/{code_digits}"
        # Trim everything up to and including the code token.
        rest = text.split(token, 1)[1].lstrip(" -")
        return ErrorEntry(
            code=code,
            severity=_SEVERITY[sev_prefix],
            message=rest,
            suggested_action=CODE_CATALOGUE.get(code, ""),
            raw=text,
        )
    return None


def parse_error_log_text(content: str) -> list[ErrorEntry]:
    """Parse a `floerror.log` body into structured entries."""
    entries: list[ErrorEntry] = []
    for line in content.splitlines():
        entry = parse_error_line(line)
        if entry is not None:
            entries.append(entry)
    return entries


def parse_logfile_xml(path: str) -> list[ErrorEntry]:
    """Parse a Flotherm GUI session log XML into structured entries.

    Flotherm writes `<install>\\WinXP\\bin\\LogFiles\\logFile<ts>.xml` per
    GUI session (5 retained). Each diagnostic appears as
    `<message text="ERROR …"/>`. Flotherm leaves these files without a
    closing `</xml_log_file>` tag — both during a live session and (often)
    after exit — so a strict ``ET.parse`` raises
    ``ParseError: no element found``. Try the strict parse first; on
    failure, append a synthetic close tag and retry.
    """
    from xml.etree import ElementTree as ET

    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return []
    if not text.strip():
        return []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        try:
            root = ET.fromstring(text + "\n</xml_log_file>")
        except ET.ParseError:
            return []
    entries: list[ErrorEntry] = []
    for el in root.iter("message"):
        entry = parse_error_line(el.get("text") or "")
        if entry is not None:
            entries.append(entry)
    return entries


def read_floerror_log(workspace: str) -> tuple[str, list[str], list[str]]:
    """Read `floerror.log`; return (full_content, fatal_lines, warning_lines).

    Backward-compatible signature. Fatal/warning lists carry raw lines whose
    parsed entry maps to a fatal code (see :data:`FATAL_CODES`) or a legacy
    floserv RunTable warning pattern.
    """
    logpath = os.path.join(workspace, "floerror.log")
    if not os.path.isfile(logpath):
        return "", [], []
    with suppress(OSError):
        content = open(logpath, encoding="utf-8", errors="replace").read()
        entries = parse_error_log_text(content)
        fatals = [e.raw for e in entries if e.code in FATAL_CODES]
        warns = [
            line.strip()
            for line in content.splitlines()
            if any(p in line for p in _LEGACY_WARNING_PATTERNS)
        ]
        return content, fatals, warns
    return "", [], []


def parse_error_log(workspace: str) -> list[dict]:
    """Read `floerror.log` and return structured entries as plain dicts.

    Plain dicts (rather than dataclass instances) so the result can flow
    straight into JSON / IPC payloads. Each item carries
    ``{code, severity, message, suggested_action, raw}``.
    """
    logpath = os.path.join(workspace, "floerror.log")
    if not os.path.isfile(logpath):
        return []
    try:
        with open(logpath, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return []
    return [asdict(e) for e in parse_error_log_text(content)]
