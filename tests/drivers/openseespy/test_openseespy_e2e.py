"""Tier 4: Real OpenSeesPy E2E — cantilever beam tip deflection."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _available() -> bool:
    try:
        from sim.drivers.openseespy import OpenSeesPyDriver
        return OpenSeesPyDriver().connect().status == "ok"
    except Exception:
        return False


_skip = pytest.mark.skipif(not _available(), reason="openseespy not installed")

EXECUTION_DIR = Path(__file__).parent.parent.parent / "execution" / "openseespy"


@_skip
@pytest.mark.integration
class TestOpenSeesPyCantilever:
    def test_e2e_cantilever(self):
        script = EXECUTION_DIR / "cantilever_beam.py"
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
                    result = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
        assert result is not None, f"No JSON: {proc.stdout[:500]}"
        assert result["ok"] is True
        assert result["analyze_status"] == 0

        # Analytical tip deflection = -1.6667e-3 m
        tip = result["tip_disp_m"]
        assert -1.7e-3 < tip < -1.6e-3, (
            f"tip_disp={tip} outside [-1.7e-3, -1.6e-3]"
        )
        assert result["rel_error"] < 0.01

    def test_py_lint(self):
        from sim.drivers.openseespy import OpenSeesPyDriver
        d = OpenSeesPyDriver()
        fx = Path(__file__).parent.parent.parent / "fixtures" / "openseespy_good.py"
        assert d.lint(fx).ok is True

    def test_py_detect(self):
        from sim.drivers.openseespy import OpenSeesPyDriver
        d = OpenSeesPyDriver()
        fx = Path(__file__).parent.parent.parent / "fixtures" / "openseespy_good.py"
        assert d.detect(fx) is True
