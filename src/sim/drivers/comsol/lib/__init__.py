"""Cross-platform COMSOL helpers — pure-Python utilities that walk a live
COMSOL Java model tree to produce human-readable summaries.

Like `flotherm/lib/`, this subpackage holds code that can be exercised
on macOS / Linux without COMSOL installed (the live-tree code paths are
mocked in unit tests). The boundary mirrors the deferred-package
convention: when this grows past ~1500 LOC or a second consumer wants
the API, it migrates to `sim-comsol` on PyPI.
"""
from __future__ import annotations

from sim.drivers.comsol.lib.describe import describe, format_text
from sim.drivers.comsol.lib.mph_inspect import (
    ModelInfo,
    MphArchive,
    MphEntry,
    format_summary,
    inspect_mph,
    mph_diff,
)

__all__ = [
    "describe",
    "format_text",
    "ModelInfo",
    "MphArchive",
    "MphEntry",
    "format_summary",
    "inspect_mph",
    "mph_diff",
]
