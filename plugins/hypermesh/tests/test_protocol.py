from __future__ import annotations

from sim.testing import assert_protocol_conformance
from sim_plugin_hypermesh import HyperMeshDriver


def test_protocol_conformance() -> None:
    assert_protocol_conformance(HyperMeshDriver)
