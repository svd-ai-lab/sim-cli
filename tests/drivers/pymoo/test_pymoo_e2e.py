"""Tier 4: Real pymoo E2E — ZDT1 with NSGA-II."""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
import pytest


def _available() -> bool:
    try:
        from sim.drivers.pymoo import PymooDriver
        return PymooDriver().connect().status == "ok"
    except Exception:
        return False


_skip = pytest.mark.skipif(not _available(), reason="pymoo not installed")
EXEC = Path(__file__).parent.parent.parent / "execution" / "pymoo"


@_skip
@pytest.mark.integration
class TestPymooZDT1:
    def test_e2e(self):
        proc = subprocess.run(
            [sys.executable, str(EXEC / "zdt1_nsga2.py")],
            capture_output=True, text=True, timeout=120,
        )
        assert proc.returncode == 0, proc.stderr[:500]
        result = None
        for line in reversed(proc.stdout.strip().splitlines()):
            if line.strip().startswith("{"):
                try: result = json.loads(line.strip()); break
                except json.JSONDecodeError: continue
        assert result is not None and result["ok"] is True
        assert result["n_pareto"] >= 20
        assert result["f1_min"] < 0.05
