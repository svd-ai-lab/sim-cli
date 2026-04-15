"""Tier 1 protocol-compliance tests for the pyvista driver."""
from __future__ import annotations

from pathlib import Path

import pytest

from sim.drivers.pyvista import PyvistaDriver

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"


class TestDetect:
    def setup_method(self):
        self.driver = PyvistaDriver()

    def test_detect_good(self):
        assert self.driver.detect(FIXTURES / "pyvista_good.py") is True

    def test_detect_no_import(self):
        assert self.driver.detect(FIXTURES / "pyvista_no_import.py") is False

    def test_detect_unsupported(self):
        assert self.driver.detect(FIXTURES / "not_simulation.py") is False

    def test_detect_missing(self):
        assert self.driver.detect(Path("/no/such.py")) is False


class TestLint:
    def setup_method(self):
        self.driver = PyvistaDriver()

    def test_lint_good(self):
        assert self.driver.lint(FIXTURES / "pyvista_good.py").ok is True

    def test_lint_no_import_is_error(self):
        r = self.driver.lint(FIXTURES / "pyvista_no_import.py")
        assert r.ok is False

    def test_lint_no_read_is_warning(self):
        r = self.driver.lint(FIXTURES / "pyvista_no_read.py")
        assert r.ok is True
        assert any(d.level == "warning" for d in r.diagnostics)

    def test_lint_syntax_error(self):
        r = self.driver.lint(FIXTURES / "pyvista_syntax_error.py")
        assert r.ok is False

    def test_lint_unsupported_suffix(self):
        import os, tempfile
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            p = Path(f.name)
        try:
            assert self.driver.lint(p).ok is False
        finally:
            os.unlink(p)


class TestConnect:
    def test_not_installed(self, monkeypatch):
        d = PyvistaDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [])
        assert d.connect().status == "not_installed"

    def test_found(self, monkeypatch):
        from sim.driver import SolverInstall
        d = PyvistaDriver()
        monkeypatch.setattr(
            d, "detect_installed",
            lambda: [SolverInstall(
                name="pyvista", version="0.47", path="/x", source="test",
                extra={"python": "/x/python", "raw_version": "0.47.3"},
            )],
        )
        assert d.connect().status == "ok"


class TestParseOutput:
    def setup_method(self):
        self.driver = PyvistaDriver()

    def test_last_json(self):
        stdout = 'info\n{"n_points": 1024, "n_cells": 2048}\n'
        assert self.driver.parse_output(stdout)["n_points"] == 1024

    def test_no_json(self):
        assert self.driver.parse_output("nothing") == {}


class TestRunFile:
    def test_raises_when_not_installed(self, monkeypatch):
        d = PyvistaDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [])
        with pytest.raises(RuntimeError, match="(?i)pyvista"):
            d.run_file(FIXTURES / "pyvista_good.py")

    def test_rejects_unsupported(self, monkeypatch):
        from sim.driver import SolverInstall
        d = PyvistaDriver()
        monkeypatch.setattr(
            d, "detect_installed",
            lambda: [SolverInstall(
                name="pyvista", version="0.47", path="/x", source="test",
                extra={"python": "/x/python"},
            )],
        )
        import os, tempfile
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            p = Path(f.name)
        try:
            with pytest.raises(RuntimeError, match="(?i)pyvista"):
                d.run_file(p)
        finally:
            os.unlink(p)
