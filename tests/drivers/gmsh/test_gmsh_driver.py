"""Tier 1 protocol-compliance tests for the Gmsh driver."""
from __future__ import annotations

from pathlib import Path

import pytest

from sim.drivers.gmsh import GmshDriver

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"


class TestDetect:
    def setup_method(self):
        self.driver = GmshDriver()

    def test_detect_good_geo(self):
        assert self.driver.detect(FIXTURES / "gmsh_good.geo") is True

    def test_detect_good_py_with_import(self):
        assert self.driver.detect(FIXTURES / "gmsh_good.py") is True

    def test_detect_py_without_import(self):
        assert self.driver.detect(FIXTURES / "gmsh_py_no_import.py") is False

    def test_detect_unrelated_file(self):
        assert self.driver.detect(FIXTURES / "not_simulation.py") is False

    def test_detect_missing_file(self):
        assert self.driver.detect(Path("/does/not/exist.geo")) is False


class TestLint:
    def setup_method(self):
        self.driver = GmshDriver()

    def test_lint_good_geo(self):
        result = self.driver.lint(FIXTURES / "gmsh_good.geo")
        assert result.ok is True

    def test_lint_good_py(self):
        result = self.driver.lint(FIXTURES / "gmsh_good.py")
        assert result.ok is True

    def test_lint_no_geom_is_warning(self):
        """A .geo with no geometry commands → warning."""
        result = self.driver.lint(FIXTURES / "gmsh_no_geom.geo")
        assert result.ok is True
        assert any(d.level == "warning" for d in result.diagnostics)

    def test_lint_py_without_import_error(self):
        result = self.driver.lint(FIXTURES / "gmsh_py_no_import.py")
        assert result.ok is False

    def test_lint_unsupported_suffix(self):
        result = self.driver.lint(FIXTURES / "not_simulation.py")
        # not_simulation.py is a .py but not a gmsh script
        assert result.ok is False


class TestConnect:
    def test_connect_not_installed(self, monkeypatch):
        driver = GmshDriver()
        monkeypatch.setattr(driver, "detect_installed", lambda: [])
        info = driver.connect()
        assert info.status == "not_installed"

    def test_connect_found(self, monkeypatch):
        from sim.driver import SolverInstall
        driver = GmshDriver()
        monkeypatch.setattr(
            driver, "detect_installed",
            lambda: [SolverInstall(
                name="gmsh", version="4.15.2",
                path="/fake/venv/bin", source="test",
                extra={"cli": "/fake/venv/bin/gmsh", "python": "/fake/venv/bin/python"},
            )],
        )
        info = driver.connect()
        assert info.status == "ok"
        assert info.version is not None


class TestParseOutput:
    def setup_method(self):
        self.driver = GmshDriver()

    def test_last_json_line(self):
        stdout = 'Info: meshing done\n{"nodes": 258, "elements": 1291}\n'
        assert self.driver.parse_output(stdout) == {"nodes": 258, "elements": 1291}

    def test_no_json(self):
        assert self.driver.parse_output("Info : Writing 'sphere.msh'") == {}


class TestRunFile:
    def test_raises_when_not_installed(self, monkeypatch):
        driver = GmshDriver()
        monkeypatch.setattr(driver, "detect_installed", lambda: [])
        with pytest.raises(RuntimeError, match="(?i)gmsh"):
            driver.run_file(FIXTURES / "gmsh_good.geo")

    def test_rejects_unsupported_suffix(self, monkeypatch):
        from sim.driver import SolverInstall
        driver = GmshDriver()
        monkeypatch.setattr(
            driver, "detect_installed",
            lambda: [SolverInstall(
                name="gmsh", version="4.15.2",
                path="/x", source="test",
                extra={"cli": "/x/gmsh", "python": "/x/python"},
            )],
        )
        # .inp is not a gmsh input
        from tempfile import NamedTemporaryFile
        with NamedTemporaryFile(suffix=".inp", delete=False) as f:
            f.write(b"*HEADING\n")
            path = Path(f.name)
        with pytest.raises(RuntimeError, match="(?i)gmsh"):
            driver.run_file(path)
