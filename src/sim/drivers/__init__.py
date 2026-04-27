"""Driver registry for sim — lazy-loaded.

Each driver is identified by a stable name and resolved lazily via importlib.
A broken import in one driver no longer crashes the entire CLI: callers that
walk the registry (`iter_drivers`) get a per-driver error; callers that ask
for a specific driver (`get_driver`) get the original ImportError raised so
they can present it directly.

Plugin discovery
----------------
External drivers register themselves via the ``sim.drivers`` entry-point group:

    [project.entry-points."sim.drivers"]
    myname = "my_pkg.module:MyDriver"

These are discovered at import time, validated, sorted by name, and **appended
after** the built-in registry. This ordering is contract: built-ins always
take precedence in `lint` first-match resolution and `solvers list` output;
externals cannot override a built-in name (collisions are logged and skipped).
External `module:Class` strings are stored as-is and resolved lazily by
`_resolve` — discovery never imports the plugin module.
"""
from __future__ import annotations

import importlib
import logging
from importlib.metadata import entry_points
from typing import Iterator

from sim.driver import DriverProtocol


log = logging.getLogger(__name__)

_ENTRY_POINT_GROUP = "sim.drivers"


# (driver_name, "module:Class") — order controls `solvers list` output order
# and `lint` first-match priority.
_BUILTIN_REGISTRY: list[tuple[str, str]] = [
    ("pybamm", "sim.drivers.pybamm:PyBaMMLDriver"),
    ("fluent", "sim.drivers.fluent:PyFluentDriver"),
    ("matlab", "sim.drivers.matlab:MatlabDriver"),
    ("comsol", "sim.drivers.comsol:ComsolDriver"),
    ("flotherm", "sim.drivers.flotherm:FlothermDriver"),
    ("ansa", "sim.drivers.ansa:AnsaDriver"),
    ("openfoam", "sim.drivers.openfoam:OpenFOAMDriver"),
    ("workbench", "sim.drivers.workbench:WorkbenchDriver"),
    ("mechanical", "sim.drivers.mechanical:MechanicalDriver"),
    ("abaqus", "sim.drivers.abaqus:AbaqusDriver"),
    ("starccm", "sim.drivers.starccm:StarccmDriver"),
    ("cfx", "sim.drivers.cfx:CfxDriver"),
    ("ls_dyna", "sim.drivers.lsdyna:LsDynaDriver"),
    ("mapdl", "sim.drivers.mapdl:MapdlDriver"),
    ("icem", "sim.drivers.icem:IcemDriver"),
    ("isaac", "sim.drivers.isaac:IsaacDriver"),
    ("newton", "sim.drivers.newton:NewtonDriver"),
    ("calculix", "sim.drivers.calculix:CalculixDriver"),
    ("gmsh", "sim.drivers.gmsh:GmshDriver"),
    ("su2", "sim.drivers.su2:Su2Driver"),
    ("lammps", "sim.drivers.lammps:LammpsDriver"),
    ("scikit_fem", "sim.drivers.scikit_fem:ScikitFemDriver"),
    ("elmer", "sim.drivers.elmer:ElmerDriver"),
    ("meshio", "sim.drivers.meshio:MeshioDriver"),
    ("pyvista", "sim.drivers.pyvista:PyvistaDriver"),
    ("pymfem", "sim.drivers.pymfem:PymfemDriver"),
    ("openseespy", "sim.drivers.openseespy:OpenSeesPyDriver"),
    ("sfepy", "sim.drivers.sfepy:SfepyDriver"),
    ("cantera", "sim.drivers.cantera:CanteraDriver"),
    ("openmdao", "sim.drivers.openmdao:OpenMDAODriver"),
    ("fipy", "sim.drivers.fipy:FipyDriver"),
    ("pymoo", "sim.drivers.pymoo:PymooDriver"),
    ("pyomo", "sim.drivers.pyomo:PyomoDriver"),
    ("simpy", "sim.drivers.simpy:SimpyDriver"),
    ("trimesh", "sim.drivers.trimesh:TrimeshDriver"),
    ("devito", "sim.drivers.devito:DevitoDriver"),
    ("coolprop", "sim.drivers.coolprop:CoolPropDriver"),
    ("scikit_rf", "sim.drivers.scikitrf:ScikitRfDriver"),
    ("pandapower", "sim.drivers.pandapower:PandapowerDriver"),
    ("paraview", "sim.drivers.paraview:ParaViewDriver"),
    ("hypermesh", "sim.drivers.hypermesh:HyperMeshDriver"),
    ("ltspice", "sim.drivers.ltspice:LTspiceDriver"),
]


def _is_valid_spec(spec: str) -> bool:
    """Cheap shape check for ``"module.path:ClassName"`` — no import."""
    if not isinstance(spec, str) or ":" not in spec:
        return False
    module_path, _, cls_name = spec.rpartition(":")
    if not module_path or not cls_name:
        return False
    if not all(p.isidentifier() for p in module_path.split(".")):
        return False
    return cls_name.isidentifier()


def _discover_external() -> list[tuple[str, str]]:
    """Find external drivers registered via the ``sim.drivers`` entry-point group.

    Validation rules (all violations are logged + skipped, never raised):
      * ``ep.value`` must look like ``"module.path:ClassName"``.
      * Names already in ``_BUILTIN_REGISTRY`` are ignored — built-in wins.
      * Duplicate external names: first-seen wins; rest skipped.

    Returns a list sorted by driver name for deterministic ordering.
    """
    builtin_names = {n for n, _ in _BUILTIN_REGISTRY}
    found: dict[str, str] = {}
    try:
        eps = entry_points(group=_ENTRY_POINT_GROUP)
    except Exception as e:  # noqa: BLE001 — entry-point machinery itself failed; degrade gracefully
        log.warning("entry_points(%s) lookup failed: %s", _ENTRY_POINT_GROUP, e)
        return []
    for ep in eps:
        name, spec = ep.name, ep.value
        if name in builtin_names:
            log.warning(
                "external driver %r (from %s) shadows a built-in; skipping",
                name, spec,
            )
            continue
        if name in found:
            log.warning(
                "duplicate external driver %r (from %s); keeping first-seen %r",
                name, spec, found[name],
            )
            continue
        if not _is_valid_spec(spec):
            log.warning(
                "external driver %r has malformed entry-point value %r; skipping",
                name, spec,
            )
            continue
        found[name] = spec
    return sorted(found.items())


_REGISTRY: list[tuple[str, str]] = _BUILTIN_REGISTRY + _discover_external()

# Cache: name -> instance. Populated on first successful resolve.
_INSTANCE_CACHE: dict[str, DriverProtocol] = {}


def driver_names() -> list[str]:
    """Stable list of all registered driver names."""
    return [n for n, _ in _REGISTRY]


def _resolve(name: str) -> DriverProtocol:
    """Import + instantiate the driver, caching the result. Raises on failure."""
    if name in _INSTANCE_CACHE:
        return _INSTANCE_CACHE[name]
    spec = next((s for n, s in _REGISTRY if n == name), None)
    if spec is None:
        raise KeyError(name)
    module_path, cls_name = spec.split(":", 1)
    mod = importlib.import_module(module_path)
    cls = getattr(mod, cls_name)
    instance = cls()
    _INSTANCE_CACHE[name] = instance
    return instance


def get_driver(name: str) -> DriverProtocol | None:
    """Lazily resolve a driver by name.

    Returns None if `name` is not a registered driver.
    Raises ImportError (or whatever the driver's import raises) if `name` is
    registered but the underlying module fails to import — callers that asked
    for a specific driver should see the real failure, not a misleading
    "no driver named X".
    """
    try:
        return _resolve(name)
    except KeyError:
        return None


def iter_drivers() -> Iterator[tuple[str, DriverProtocol | None, BaseException | None]]:
    """Walk all registered drivers, tolerating per-driver import failure.

    Yields (name, instance, error). When import fails, instance is None and
    error holds the exception. Use this for `solvers list`, `lint`
    auto-detection, or anywhere you need to enumerate without a single broken
    driver killing the walk.
    """
    for name, _ in _REGISTRY:
        try:
            yield name, _resolve(name), None
        except Exception as e:  # noqa: BLE001 — any import-time failure; KeyboardInterrupt/SystemExit propagate
            yield name, None, e
