"""Shared fixtures and skip conditions for sim-agent-flotherm tests."""
from __future__ import annotations

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

AGENT_ROOT = Path(__file__).parent.parent

# The one real runnable .pack file available from the Flotherm installation.
# This is the test oracle for all Phase A execution tests.
DEMO_PACK = Path(
    r"E:\Program Files (x86)\Siemens\SimcenterFlotherm\2504"
    r"\examples\FloSCRIPT\Demonstration Examples"
    r"\Transient Power Update\Mobile_Demo-Steady_State.pack"
)


# ---------------------------------------------------------------------------
# Skip helpers
# ---------------------------------------------------------------------------

def _flotherm_installed() -> bool:
    """Return True if Flotherm 2504 is installed and detectable."""
    try:
        from sim.drivers.flotherm import FlothermDriver
        return FlothermDriver().connect().status == "ok"
    except Exception:
        return False


def _demo_pack_exists() -> bool:
    return DEMO_PACK.exists()


# ---------------------------------------------------------------------------
# Pytest markers
# ---------------------------------------------------------------------------

def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "flotherm: mark test as requiring Flotherm installation",
    )
    config.addinivalue_line(
        "markers",
        "slow: mark test as slow (real batch solve may take minutes)",
    )
