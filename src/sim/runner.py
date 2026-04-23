"""Execution helpers for sim one-shot runs."""
from __future__ import annotations

import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from sim.driver import RunResult


# Generic error patterns that indicate failure regardless of exit code.
# Each driver can add solver-specific patterns on top.
_GENERIC_ERROR_PATTERNS = [
    re.compile(r"^Traceback \(most recent call last\):", re.MULTILINE),
    re.compile(r"^(Error|ERROR|Fatal error|FATAL):", re.MULTILINE),
    re.compile(r"(?:Exception|Error): .+", re.MULTILINE),
]


def detect_output_errors(stdout: str, stderr: str) -> list[str]:
    """Scan stdout and stderr for generic error patterns.

    Returns a list of human-readable error descriptions found.
    Drivers should call this first, then append solver-specific checks.
    """
    errors: list[str] = []
    for text, source in [(stderr, "stderr"), (stdout, "stdout")]:
        if not text:
            continue
        for pat in _GENERIC_ERROR_PATTERNS:
            m = pat.search(text)
            if m:
                # Extract the matching line plus context
                line = m.group(0)[:200]
                errors.append(f"[{source}] {line}")
    return errors


def run_subprocess(
    command: list[str],
    *,
    script: Path,
    solver: str,
) -> RunResult:
    """Execute a subprocess and capture a RunResult."""
    start = time.monotonic()
    proc = subprocess.run(
        command,
        capture_output=True,
        text=True,
    )
    duration = time.monotonic() - start

    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()
    errors = detect_output_errors(stdout, stderr)

    # If exit code is 0 but errors detected in output, override to 1
    exit_code = proc.returncode
    if exit_code == 0 and errors:
        exit_code = 1

    return RunResult(
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_s=round(duration, 3),
        script=str(script),
        solver=solver,
        timestamp=datetime.now(timezone.utc).isoformat(),
        errors=errors,
    )


def execute_script(
    script: Path,
    python: str | None = None,
    solver: str = "unknown",
    driver=None,
) -> RunResult:
    """Execute a script, delegating to the solver driver when available."""
    if driver is not None:
        return driver.run_file(script)

    if python is None:
        python = sys.executable

    result = run_subprocess(
        [python, str(script)],
        script=script,
        solver=solver,
    )
    _attach_probes(result, solver)
    return result


def _attach_probes(result: RunResult, solver: str) -> None:
    """Run generic probes on a completed one-shot RunResult (in-place).

    Probes applicable to subprocess one-shot runs:
      #1  ProcessMetaProbe   — exit_code + wall_time (from result fields)
      #3  StdoutJsonTailProbe — last JSON line on stdout
      #3+ PythonTracebackProbe — tracebacks in stderr
      #5  DomainExceptionMapProbe — upgrades python.* exception codes

    Not applicable to one-shot runs (no live session, no workdir baseline):
      #1+ RuntimeTimeoutProbe — no hung-snippet detection for subprocesses
      #4  SdkAttributeProbe  — no live session namespace
      #9  WorkdirDiffProbe   — skipped (workdir_before=None → applies()=False)
    """
    try:
        from sim.inspect import InspectCtx, collect_diagnostics, generic_probes
        ctx = InspectCtx(
            stdout=result.stdout,
            stderr=result.stderr,
            workdir=str(Path(result.script).parent),
            wall_time_s=result.duration_s,
            exit_code=result.exit_code,
            driver_name=solver,
            session_ns={},
            workdir_before=None,  # no baseline → WorkdirDiffProbe skipped
        )
        diags, arts = collect_diagnostics(generic_probes(), ctx)
        result.diagnostics = [d.to_dict() for d in diags]
        result.artifacts = [a.to_dict() for a in arts]
    except Exception:
        pass  # probes must never break the run path
