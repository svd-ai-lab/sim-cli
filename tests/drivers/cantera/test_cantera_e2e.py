"""Tier 4: Real Cantera E2E — adiabatic flame temperature."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _available() -> bool:
    try:
        from sim.drivers.cantera import CanteraDriver
        return CanteraDriver().connect().status == "ok"
    except Exception:
        return False


_skip = pytest.mark.skipif(not _available(), reason="cantera not installed")
EXECUTION_DIR = Path(__file__).parent.parent.parent / "execution" / "cantera"


@_skip
@pytest.mark.integration
class TestCanteraAdiabaticFlame:
    def test_e2e(self):
        script = EXECUTION_DIR / "adiabatic_flame.py"
        proc = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, timeout=60,
        )
        assert proc.returncode == 0, proc.stderr[:500]
        result = None
        for line in reversed(proc.stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    result = json.loads(line); break
                except json.JSONDecodeError:
                    continue
        assert result is not None
        assert result["ok"] is True
        assert 2150 < result["T_ad_K"] < 2300
