"""The lib/ subpackage must import without pywinauto / ctypes.

This test runs on macOS / Linux without Flotherm installed. It guards the
architectural decision: the cross-platform pieces stay extractable to a
standalone `sim-flotherm` package once the trigger conditions hit.
"""
from __future__ import annotations

import sys


def test_lib_imports_without_pywinauto():
    # Re-import the lib package and snapshot loaded modules. None of the
    # GUI-coupled or Windows-only deps should appear.
    import sim.drivers.flotherm.lib  # noqa: F401
    forbidden = {"pywinauto", "ctypes.wintypes", "win32api", "win32con"}
    found = forbidden.intersection(sys.modules)
    assert not found, f"lib/ pulled in GUI deps: {found}"


def test_public_surface():
    from sim.drivers.flotherm.lib import (
        build_custom,
        build_solve_and_save,
        build_solve_scenario,
        lint_floscript,
        lint_floxml,
        lint_pack,
        pack_project_dir,
        pack_project_name,
        parse_error_line,
        parse_error_log,
        parse_error_log_text,
        parse_logfile_xml,
        read_floerror_log,
    )

    for fn in (build_custom, build_solve_and_save, build_solve_scenario,
               lint_floscript, lint_floxml, lint_pack, pack_project_dir,
               pack_project_name, parse_error_line, parse_error_log,
               parse_error_log_text, parse_logfile_xml, read_floerror_log):
        assert callable(fn)
