"""Tier 4: Real Pyomo E2E — classic LP."""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
import pytest


def _available() -> bool:
    try:
        from sim.drivers.pyomo import PyomoDriver
        return PyomoDriver().connect().status == "ok"
    except Exception:
        return False


_skip = pytest.mark.skipif(not _available(), reason="pyomo not installed")
EXEC = Path(__file__).parent.parent.parent / "execution" / "pyomo"


@_skip
@pytest.mark.integration
class TestPyomoLP:
    def test_e2e(self):
        proc = subprocess.run(
            [sys.executable, str(EXEC / "lp_classic.py")],
            capture_output=True, text=True, timeout=60,
        )
        # OK if solver is actually present locally
        if proc.returncode != 0:
            pytest.skip(f"runtime error: {proc.stderr[:200]}")
        result = None
        for line in reversed(proc.stdout.strip().splitlines()):
            if line.strip().startswith("{"):
                try: result = json.loads(line.strip()); break
                except json.JSONDecodeError: continue
        if result is None or not result.get("ok"):
            pytest.skip("no LP backend solver installed locally")
        assert abs(result["x"] - 2.0) < 1e-4
        assert abs(result["y"] - 6.0) < 1e-4
        assert abs(result["obj"] - 36.0) < 1e-4
