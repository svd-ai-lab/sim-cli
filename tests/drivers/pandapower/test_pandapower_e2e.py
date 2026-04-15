"""Tier 4: Real pandapower E2E — 2-bus power flow."""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
import pytest


def _available() -> bool:
    try:
        from sim.drivers.pandapower import PandapowerDriver
        return PandapowerDriver().connect().status == "ok"
    except Exception:
        return False


_skip = pytest.mark.skipif(not _available(), reason="pandapower not installed")
EXEC = Path(__file__).parent.parent.parent / "execution" / "pandapower"


@_skip
@pytest.mark.integration
class TestPandapowerPF:
    def test_e2e(self):
        proc = subprocess.run(
            [sys.executable, str(EXEC / "two_bus_pf.py")],
            capture_output=True, text=True, timeout=60,
        )
        assert proc.returncode == 0, proc.stderr[:500]
        result = None
        for line in reversed(proc.stdout.strip().splitlines()):
            if line.strip().startswith("{"):
                try: result = json.loads(line.strip()); break
                except json.JSONDecodeError: continue
        assert result is not None and result["ok"] is True
        assert 0.95 <= result["vm_pu_b2"] <= 1.0
