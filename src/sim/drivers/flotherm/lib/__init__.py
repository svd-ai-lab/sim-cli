"""Cross-platform Flotherm helpers — file format, lint, FloSCRIPT generation.

This subpackage holds pure-Python code with no `pywinauto` / `ctypes` imports,
so it runs on macOS / Linux without Flotherm installed and is unit-testable
in CI on any host.

The boundary is deliberate: when `lib/` grows past ~1500 LOC or a second
consumer (Jupyter, sim-benchmark, third-party agent) wants the API, this
moves to a standalone `sim-flotherm` PyPI package via
`git mv lib/ sim-flotherm/src/sim_flotherm/`.

Until then the GUI driver (`driver.py`, `_win32_backend.py`) imports from
here.
"""
from __future__ import annotations

from sim.drivers.flotherm.lib.error_log import read_floerror_log
from sim.drivers.flotherm.lib.floscript import (
    build_custom,
    build_solve_and_save,
    build_solve_scenario,
    lint_floscript,
)
from sim.drivers.flotherm.lib.floxml import lint_floxml
from sim.drivers.flotherm.lib.floxml_builder import (
    Ambient,
    Cuboid,
    FixedTemperature,
    Fluid,
    HeatSource,
    IsotropicMaterial,
    Project,
    SolutionDomain,
)
from sim.drivers.flotherm.lib.msp_field import (
    MspFieldError,
    list_fields,
    read_mesh_dims,
    read_msp_field,
)
from sim.drivers.flotherm.lib.pack import (
    lint_pack,
    pack_project_dir,
    pack_project_name,
)

__all__ = [
    "Ambient",
    "Cuboid",
    "FixedTemperature",
    "Fluid",
    "HeatSource",
    "IsotropicMaterial",
    "MspFieldError",
    "Project",
    "SolutionDomain",
    "build_custom",
    "build_solve_and_save",
    "build_solve_scenario",
    "lint_floscript",
    "lint_floxml",
    "lint_pack",
    "list_fields",
    "pack_project_dir",
    "pack_project_name",
    "read_floerror_log",
    "read_mesh_dims",
    "read_msp_field",
]
