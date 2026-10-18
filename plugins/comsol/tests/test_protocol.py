"""Protocol-conformance test — plugged into sim-cli's shared harness."""
from __future__ import annotations

from sim.testing import assert_protocol_conformance
from sim_plugin_comsol import ComsolDriver


def test_protocol_conformance() -> None:
    """Drives every conformance check sim-cli requires of a plugin driver."""
    assert_protocol_conformance(ComsolDriver)


def test_lint_missing_file_returns_diagnostic(tmp_path) -> None:
    """Missing files should be lint failures, not uncaught IO errors."""
    result = ComsolDriver().lint(tmp_path / "missing.py")

    assert result.ok is False
    assert result.diagnostics
    assert result.diagnostics[0].level == "error"
