"""Tier 4: Real scikit-rf E2E — short / open / match loads."""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
import pytest


def _available() -> bool:
    try:
        from sim.drivers.scikitrf import ScikitRfDriver
        return ScikitRfDriver().connect().status == "ok"
    except Exception:
        return False


_skip = pytest.mark.skipif(not _available(), reason="scikit-rf not installed")
EXEC = Path(__file__).parent.parent.parent / "execution" / "scikitrf"


@_skip
@pytest.mark.integration
class TestScikitRfLoads:
    def test_e2e(self):
        proc = subprocess.run(
            [sys.executable, str(EXEC / "short_load.py")],
            capture_output=True, text=True, timeout=60,
        )
        assert proc.returncode == 0, proc.stderr[:500]
        result = None
        for line in reversed(proc.stdout.strip().splitlines()):
            if line.strip().startswith("{"):
                try: result = json.loads(line.strip()); break
                except json.JSONDecodeError: continue
        assert result is not None and result["ok"] is True
        assert abs(result["S11_short_re"] + 1.0) < 1e-12
        assert abs(result["S11_open_re"] - 1.0) < 1e-12
        assert abs(result["S11_match_re"]) < 1e-12
