"""Protocol-conformance test — plugged into sim-cli's shared harness."""
from __future__ import annotations

from sim.testing import assert_protocol_conformance
from sim_plugin_comsol import ComsolDriver


def test_protocol_conformance() -> None:
    """Drives every conformance check sim-cli requires of a plugin driver."""
    assert_protocol_conformance(ComsolDriver)
