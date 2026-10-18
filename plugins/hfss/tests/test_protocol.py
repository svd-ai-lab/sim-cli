"""Protocol-conformance test plugged into sim-cli's shared harness."""
from __future__ import annotations

from sim.testing import assert_protocol_conformance
from sim_plugin_hfss import HfssDriver


def test_protocol_conformance() -> None:
    assert_protocol_conformance(HfssDriver)
