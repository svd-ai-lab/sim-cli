"""`floerror.log` parsing — fatal + warning extraction."""
from __future__ import annotations

import os
from contextlib import suppress

_FATAL_PATTERNS = ("E/11029", "E/9012")
_WARNING_PATTERNS = ("registerStart runTable exception",)


def read_floerror_log(workspace: str) -> tuple[str, list[str], list[str]]:
    """Read floerror.log; return (full_content, fatal_errors, warnings)."""
    logpath = os.path.join(workspace, "floerror.log")
    if not os.path.isfile(logpath):
        return "", [], []
    with suppress(OSError):
        content = open(logpath, encoding="utf-8", errors="replace").read()
        fatals = [l.strip() for l in content.splitlines()
                  if any(p in l for p in _FATAL_PATTERNS)]
        warns = [l.strip() for l in content.splitlines()
                 if any(p in l for p in _WARNING_PATTERNS)]
        return content, fatals, warns
    return "", [], []
