"""Driver registry for sim."""
from __future__ import annotations

from sim.driver import DriverProtocol
from sim.drivers.pybamm import PyBaMMLDriver
from sim.drivers.fluent import PyFluentDriver
from sim.drivers.matlab import MatlabDriver
from sim.drivers.comsol import ComsolDriver
from sim.drivers.flotherm import FlothermDriver
from sim.drivers.ansa import AnsaDriver
from sim.drivers.openfoam import OpenFOAMDriver
from sim.drivers.workbench import WorkbenchDriver
from sim.drivers.mechanical import MechanicalDriver
from sim.drivers.abaqus import AbaqusDriver
from sim.drivers.starccm import StarccmDriver

DRIVERS: list[DriverProtocol] = [
    PyBaMMLDriver(),
    PyFluentDriver(),
    MatlabDriver(),
    ComsolDriver(),
    FlothermDriver(),
    AnsaDriver(),
    OpenFOAMDriver(),
    WorkbenchDriver(),
    MechanicalDriver(),
    AbaqusDriver(),
    StarccmDriver(),
]


def get_driver(name: str) -> DriverProtocol | None:
    """Get a driver by name."""
    for d in DRIVERS:
        if d.name == name:
            return d
    return None
