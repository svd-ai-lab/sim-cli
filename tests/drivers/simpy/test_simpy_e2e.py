"""Tier 4: Real SimPy E2E — M/M/1 queue."""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
import pytest


def _available() -> bool:
    try:
        from sim.drivers.simpy import SimpyDriver
        return SimpyDriver().connect().status == "ok"
    except Exception:
        return False


_skip = pytest.mark.skipif(not _available(), reason="simpy not installed")
EXEC = Path(__file__).parent.parent.parent / "execution" / "simpy"


@_skip
@pytest.mark.integration
class TestSimpyMM1:
    def test_e2e(self):
        proc = subprocess.run(
            [sys.executable, str(EXEC / "mm1_queue.py")],
            capture_output=True, text=True, timeout=120,
        )
        assert proc.returncode == 0, proc.stderr[:500]
        result = None
        for line in reversed(proc.stdout.strip().splitlines()):
            if line.strip().startswith("{"):
                try: result = json.loads(line.strip()); break
                except json.JSONDecodeError: continue
        assert result is not None and result["ok"] is True
        assert abs(result["L_observed"] - 2.0) / 2.0 < 0.15
