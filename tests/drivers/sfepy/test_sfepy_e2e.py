"""Tier 4: Real SfePy E2E — Poisson on unit square."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _available() -> bool:
    try:
        from sim.drivers.sfepy import SfepyDriver
        return SfepyDriver().connect().status == "ok"
    except Exception:
        return False


_skip = pytest.mark.skipif(not _available(), reason="sfepy not installed")
EXECUTION_DIR = Path(__file__).parent.parent.parent / "execution" / "sfepy"


@_skip
@pytest.mark.integration
class TestSfepyPoisson:
    def test_e2e_poisson(self):
        script = EXECUTION_DIR / "poisson_unit_square.py"
        assert script.is_file()
        proc = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, timeout=120,
        )
        assert proc.returncode == 0, f"E2E failed: {proc.stderr[:500]}"
        result = None
        for line in reversed(proc.stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    result = json.loads(line); break
                except json.JSONDecodeError:
                    continue
        assert result is not None, f"No JSON: {proc.stdout[-500:]}"
        assert result["ok"] is True
        assert 0.06 < result["u_max"] < 0.09
        assert result["rel_error"] < 0.05
