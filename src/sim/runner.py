"""Execution helpers for sim one-shot runs."""
from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from sim.driver import RunResult


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

    return RunResult(
        exit_code=proc.returncode,
        stdout=proc.stdout.strip(),
        stderr=proc.stderr.strip(),
        duration_s=round(duration, 3),
        script=str(script),
        solver=solver,
        timestamp=datetime.now(timezone.utc).isoformat(),
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

    return run_subprocess(
        [python, str(script)],
        script=script,
        solver=solver,
    )
