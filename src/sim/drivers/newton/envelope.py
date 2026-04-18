"""Output / error envelope helpers for sim's newton driver subprocess entry.

Stable contract:
  - emit_envelope(data) writes one line of {"schema":"sim/newton/v1","data":...} to stdout
  - fail(code, msg) writes {"schema":"sim/newton/v1","error":{...}} to stderr and exits

Exit codes:
  0  ok
  2  user / argument error (bad recipe shape, missing script)
  3  Newton / Warp runtime error
  4  missing optional dependency
  5  timeout (raised by caller, not by this module)
"""
from __future__ import annotations

import json
import sys
from typing import Any, NoReturn

SCHEMA = "sim/newton/v1"

EXIT_OK = 0
EXIT_USER_ERROR = 2
EXIT_RUNTIME_ERROR = 3
EXIT_MISSING_DEP = 4
EXIT_TIMEOUT = 5


def emit_envelope(data: Any) -> None:
    """Write one envelope line to stdout. Exactly one line, no leading noise."""
    sys.stdout.write(json.dumps({"schema": SCHEMA, "data": data}, default=str))
    sys.stdout.write("\n")
    sys.stdout.flush()


def fail(
    code: int,
    message: str,
    *,
    hint: str | None = None,
    error_code: str | None = None,
) -> NoReturn:
    """Write an error envelope to stderr and exit with `code`."""
    envelope = {
        "schema": SCHEMA,
        "error": {
            "code": error_code or _default_error_code(code),
            "message": message,
        },
    }
    if hint:
        envelope["error"]["hint"] = hint
    sys.stderr.write(json.dumps(envelope))
    sys.stderr.write("\n")
    sys.stderr.flush()
    sys.exit(code)


def _default_error_code(exit_code: int) -> str:
    return {
        EXIT_USER_ERROR: "user_error",
        EXIT_RUNTIME_ERROR: "runtime_error",
        EXIT_MISSING_DEP: "missing_dependency",
        EXIT_TIMEOUT: "timeout",
    }.get(exit_code, "error")
