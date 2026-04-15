"""Tier 4: Real Trimesh E2E."""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
import pytest


def _available() -> bool:
    try:
        from sim.drivers.trimesh import TrimeshDriver
        return TrimeshDriver().connect().status == "ok"
    except Exception:
        return False


_skip = pytest.mark.skipif(not _available(), reason="trimesh not installed")
EXEC = Path(__file__).parent.parent.parent / "execution" / "trimesh"


@_skip
@pytest.mark.integration
class TestTrimeshProps:
    def test_e2e(self):
        proc = subprocess.run(
            [sys.executable, str(EXEC / "sphere_box_props.py")],
            capture_output=True, text=True, timeout=60,
        )
        assert proc.returncode == 0, proc.stderr[:500]
        result = None
        for line in reversed(proc.stdout.strip().splitlines()):
            if line.strip().startswith("{"):
                try: result = json.loads(line.strip()); break
                except json.JSONDecodeError: continue
        assert result is not None and result["ok"] is True
        assert abs(result["box_volume"] - 24.0) < 1e-9
        assert result["sphere_watertight"] is True
