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

from .error_log import (
    CODE_CATALOGUE,
    FATAL_CODES,
    ErrorEntry,
    parse_error_line,
    parse_error_log,
    parse_error_log_text,
    parse_logfile_xml,
    read_floerror_log,
)
from .floscript import (
    build_custom,
    build_project_save,
    build_project_save_as,
    build_solve_and_save,
    build_solve_scenario,
    build_start_record_script,
    build_stop_record_script,
    lint_floscript,
)
from .floxml import lint_floxml
from .floxml_builder import (
    Ambient,
    Cuboid,
    FixedTemperature,
    Fluid,
    HeatSource,
    IsotropicMaterial,
    Project,
    SolutionDomain,
)
from .msp_field import (
    MspFieldError,
    list_fields,
    read_mesh_dims,
    read_msp_field,
)
from .pack import (
    lint_pack,
    pack_project_dir,
    pack_project_name,
)

__all__ = [
    "Ambient",
    "CODE_CATALOGUE",
    "Cuboid",
    "ErrorEntry",
    "FATAL_CODES",
    "FixedTemperature",
    "Fluid",
    "HeatSource",
    "IsotropicMaterial",
    "MspFieldError",
    "Project",
    "SolutionDomain",
    "build_custom",
    "build_project_save",
    "build_project_save_as",
    "build_solve_and_save",
    "build_solve_scenario",
    "build_start_record_script",
    "build_stop_record_script",
    "lint_floscript",
    "lint_floxml",
    "lint_pack",
    "list_fields",
    "pack_project_dir",
    "pack_project_name",
    "parse_error_line",
    "parse_error_log",
    "parse_error_log_text",
    "parse_logfile_xml",
    "read_floerror_log",
    "read_mesh_dims",
    "read_msp_field",
]
