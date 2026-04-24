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
from sim.drivers.cfx import CfxDriver
from sim.drivers.lsdyna import LsDynaDriver
from sim.drivers.mapdl import MapdlDriver
from sim.drivers.icem import IcemDriver
from sim.drivers.isaac import IsaacDriver
from sim.drivers.newton import NewtonDriver
from sim.drivers.calculix import CalculixDriver
from sim.drivers.gmsh import GmshDriver
from sim.drivers.su2 import Su2Driver
from sim.drivers.lammps import LammpsDriver
from sim.drivers.scikit_fem import ScikitFemDriver
from sim.drivers.elmer import ElmerDriver
from sim.drivers.meshio import MeshioDriver
from sim.drivers.pyvista import PyvistaDriver
from sim.drivers.pymfem import PymfemDriver
from sim.drivers.openseespy import OpenSeesPyDriver
from sim.drivers.sfepy import SfepyDriver
from sim.drivers.cantera import CanteraDriver
from sim.drivers.openmdao import OpenMDAODriver
from sim.drivers.fipy import FipyDriver
from sim.drivers.pymoo import PymooDriver
from sim.drivers.pyomo import PyomoDriver
from sim.drivers.simpy import SimpyDriver
from sim.drivers.trimesh import TrimeshDriver
from sim.drivers.devito import DevitoDriver
from sim.drivers.coolprop import CoolPropDriver
from sim.drivers.scikitrf import ScikitRfDriver
from sim.drivers.pandapower import PandapowerDriver
from sim.drivers.paraview import ParaViewDriver
from sim.drivers.hypermesh import HyperMeshDriver
from sim.drivers.ltspice import LTspiceDriver

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
    CfxDriver(),
    LsDynaDriver(),
    MapdlDriver(),
    IcemDriver(),
    IsaacDriver(),
    NewtonDriver(),
    CalculixDriver(),
    GmshDriver(),
    Su2Driver(),
    LammpsDriver(),
    ScikitFemDriver(),
    ElmerDriver(),
    MeshioDriver(),
    PyvistaDriver(),
    PymfemDriver(),
    OpenSeesPyDriver(),
    SfepyDriver(),
    CanteraDriver(),
    OpenMDAODriver(),
    FipyDriver(),
    PymooDriver(),
    PyomoDriver(),
    SimpyDriver(),
    TrimeshDriver(),
    DevitoDriver(),
    CoolPropDriver(),
    ScikitRfDriver(),
    PandapowerDriver(),
    ParaViewDriver(),
    HyperMeshDriver(),
    LTspiceDriver(),
]


def get_driver(name: str) -> DriverProtocol | None:
    """Get a driver by name."""
    for d in DRIVERS:
        if d.name == name:
            return d
    return None
