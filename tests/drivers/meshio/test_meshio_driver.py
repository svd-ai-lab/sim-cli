"""Tier 1 protocol-compliance tests for the meshio driver."""
from __future__ import annotations

from pathlib import Path

import pytest

from sim.drivers.meshio import MeshioDriver

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"


class TestDetect:
    def setup_method(self):
        self.driver = MeshioDriver()

    def test_detect_good_py(self):
        assert self.driver.detect(FIXTURES / "meshio_good.py") is True

    def test_detect_no_import(self):
        assert self.driver.detect(FIXTURES / "meshio_no_import.py") is False

    def test_detect_unsupported_suffix(self):
        assert self.driver.detect(FIXTURES / "not_simulation.py") is False

    def test_detect_syntax_error_still_detects(self):
        assert self.driver.detect(FIXTURES / "meshio_syntax_error.py") is True

    def test_detect_missing_file(self):
        assert self.driver.detect(Path("/does/not/exist.py")) is False


class TestLint:
    def setup_method(self):
        self.driver = MeshioDriver()

    def test_lint_good(self):
        assert self.driver.lint(FIXTURES / "meshio_good.py").ok is True

    def test_lint_no_import_is_error(self):
        r = self.driver.lint(FIXTURES / "meshio_no_import.py")
        assert r.ok is False

    def test_lint_no_io_is_warning(self):
        r = self.driver.lint(FIXTURES / "meshio_no_io.py")
        assert r.ok is True
        assert any(d.level == "warning" for d in r.diagnostics)

    def test_lint_syntax_error(self):
        r = self.driver.lint(FIXTURES / "meshio_syntax_error.py")
        assert r.ok is False

    def test_lint_unsupported_suffix(self):
        from tempfile import NamedTemporaryFile
        import os
        with NamedTemporaryFile(suffix=".txt", delete=False) as f:
            p = Path(f.name)
        try:
            r = self.driver.lint(p)
            assert r.ok is False
        finally:
            os.unlink(p)


class TestConnect:
    def test_not_installed(self, monkeypatch):
        driver = MeshioDriver()
        monkeypatch.setattr(driver, "detect_installed", lambda: [])
        assert driver.connect().status == "not_installed"

    def test_found(self, monkeypatch):
        from sim.driver import SolverInstall
        driver = MeshioDriver()
        monkeypatch.setattr(
            driver, "detect_installed",
            lambda: [SolverInstall(
                name="meshio", version="5.3",
                path="/fake/bin", source="test",
                extra={"python": "/fake/bin/python", "raw_version": "5.3.5"},
            )],
        )
        assert driver.connect().status == "ok"


class TestParseOutput:
    def setup_method(self):
        self.driver = MeshioDriver()

    def test_last_json_line(self):
        stdout = 'info\n{"points": 258, "cells": {"triangle": 380}}\n'
        r = self.driver.parse_output(stdout)
        assert r["points"] == 258

    def test_no_json(self):
        assert self.driver.parse_output("nothing") == {}


class TestRunFile:
    def test_raises_when_not_installed(self, monkeypatch):
        driver = MeshioDriver()
        monkeypatch.setattr(driver, "detect_installed", lambda: [])
        with pytest.raises(RuntimeError, match="(?i)meshio"):
            driver.run_file(FIXTURES / "meshio_good.py")

    def test_rejects_unsupported_suffix(self, monkeypatch):
        from sim.driver import SolverInstall
        driver = MeshioDriver()
        monkeypatch.setattr(
            driver, "detect_installed",
            lambda: [SolverInstall(
                name="meshio", version="5.3", path="/x", source="test",
                extra={"python": "/x/python"},
            )],
        )
        from tempfile import NamedTemporaryFile
        import os
        with NamedTemporaryFile(suffix=".txt", delete=False) as f:
            p = Path(f.name)
        try:
            with pytest.raises(RuntimeError, match="(?i)meshio"):
                driver.run_file(p)
        finally:
            os.unlink(p)
