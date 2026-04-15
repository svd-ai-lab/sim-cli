"""Tier 4: Real FiPy E2E — 1D steady Poisson."""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
import pytest


def _available() -> bool:
    try:
        from sim.drivers.fipy import FipyDriver
        return FipyDriver().connect().status == "ok"
    except Exception:
        return False


_skip = pytest.mark.skipif(not _available(), reason="fipy not installed")
EXEC = Path(__file__).parent.parent.parent / "execution" / "fipy"


@_skip
@pytest.mark.integration
class TestFipyPoisson:
    def test_e2e(self):
        proc = subprocess.run(
            [sys.executable, str(EXEC / "poisson_1d.py")],
            capture_output=True, text=True, timeout=60,
        )
        assert proc.returncode == 0, proc.stderr[:500]
        result = None
        for line in reversed(proc.stdout.strip().splitlines()):
            if line.strip().startswith("{"):
                try: result = json.loads(line.strip()); break
                except json.JSONDecodeError: continue
        assert result is not None and result["ok"] is True
        assert abs(result["mid_value"] - 0.49) < 0.01
