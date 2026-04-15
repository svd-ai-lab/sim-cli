"""Tier 4: Real Devito E2E — 2D heat diffusion."""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
import pytest


def _available() -> bool:
    try:
        from sim.drivers.devito import DevitoDriver
        return DevitoDriver().connect().status == "ok"
    except Exception:
        return False


_skip = pytest.mark.skipif(not _available(), reason="devito not installed")
EXEC = Path(__file__).parent.parent.parent / "execution" / "devito"


@_skip
@pytest.mark.integration
class TestDevitoDiffusion:
    def test_e2e(self):
        proc = subprocess.run(
            [sys.executable, str(EXEC / "diffusion_2d.py")],
            capture_output=True, text=True, timeout=120,
        )
        assert proc.returncode == 0, proc.stderr[:500]
        result = None
        for line in reversed(proc.stdout.strip().splitlines()):
            if line.strip().startswith("{"):
                try: result = json.loads(line.strip()); break
                except json.JSONDecodeError: continue
        assert result is not None and result["ok"] is True
        assert 5.0 < result["peak"] < 30.0
        assert result["mass_rel_error"] < 0.10
