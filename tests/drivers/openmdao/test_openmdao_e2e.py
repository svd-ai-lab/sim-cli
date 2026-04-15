"""Tier 4: Real OpenMDAO E2E — Sellar MDA."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _available() -> bool:
    try:
        from sim.drivers.openmdao import OpenMDAODriver
        return OpenMDAODriver().connect().status == "ok"
    except Exception:
        return False


_skip = pytest.mark.skipif(not _available(), reason="openmdao not installed")
EXECUTION_DIR = Path(__file__).parent.parent.parent / "execution" / "openmdao"


@_skip
@pytest.mark.integration
class TestOpenMDAOSellar:
    def test_e2e(self):
        script = EXECUTION_DIR / "sellar_mda.py"
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
        assert abs(result["y1"] - 25.588) < 0.01
        assert abs(result["y2"] - 12.058) < 0.01
