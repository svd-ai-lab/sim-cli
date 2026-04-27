"""Tier 4: Real Mechanical E2E — gated on a working Ansys install.

Skipped unless:
  - ``ansys.mechanical.core`` imports
  - ``MechanicalDriver().connect().status == "ok"`` (i.e. an Ansys install
    is discoverable via ``ansys-tools-path`` or ``AWP_ROOTxxx``)

The execution scripts under ``tests/execution/mechanical/`` are full-fat
PyMechanical workflows (launch GUI, screenshot, solve). They are not
invoked from pytest here — run them directly on a Windows host with a
licensed Ansys install. This module only verifies that ``connect()``
returns ``ok`` on such a host, as a smoke test.
"""
from __future__ import annotations

from pathlib import Path

import pytest


def _available() -> bool:
    try:
        from sim_plugin_mechanical import MechanicalDriver
        return MechanicalDriver().connect().status == "ok"
    except Exception:
        return False


_skip = pytest.mark.skipif(
    not _available(), reason="Ansys Mechanical / PyMechanical not installed"
)
EXECUTION_DIR = Path(__file__).parent / "execution" / "mechanical"


@_skip
@pytest.mark.integration
class TestMechanicalSmoke:
    def test_connect_ok(self):
        from sim_plugin_mechanical import MechanicalDriver
        info = MechanicalDriver().connect()
        assert info.status == "ok"
        assert info.solver_version is not None

    def test_execution_scripts_present(self):
        # Sanity: the bundled execution scripts shipped with the plugin.
        for name in (
            "mechanical_tdd_smoke.py",
            "mechanical_observation_coupling.py",
            "mechanical_e2e_static_structural.py",
        ):
            assert (EXECUTION_DIR / name).is_file(), name
