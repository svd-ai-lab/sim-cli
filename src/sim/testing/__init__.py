"""Test helpers for plugin authors.

The single most important export here is :func:`assert_protocol_conformance`,
which every external plugin should call from its own test suite to confirm
its driver class meets the contract sim-cli depends on.

Plugins typically pull this in via::

    # sim-plugin-<solver>/tests/test_protocol.py
    from sim.testing import assert_protocol_conformance
    from sim_plugin_<solver> import <Solver>Driver

    def test_protocol_conformance():
        assert_protocol_conformance(<Solver>Driver)

This module intentionally has zero plugin-author boilerplate beyond that.
"""
from __future__ import annotations

from .protocol_conformance import (
    assert_protocol_conformance,
    check_driver,
    ConformanceFailure,
)

__all__ = [
    "assert_protocol_conformance",
    "check_driver",
    "ConformanceFailure",
]
