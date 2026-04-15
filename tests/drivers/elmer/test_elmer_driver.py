"""Tier 1 protocol-compliance tests for the Elmer FEM driver."""
from __future__ import annotations

from pathlib import Path

import pytest

from sim.drivers.elmer import ElmerDriver

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"


class TestDetect:
    def setup_method(self):
        self.driver = ElmerDriver()

    def test_detect_good_sif(self):
        assert self.driver.detect(FIXTURES / "elmer_good.sif") is True

    def test_detect_not_sif_content(self):
        assert self.driver.detect(FIXTURES / "elmer_not_sif.sif") is False

    def test_detect_non_sif_extension(self):
        assert self.driver.detect(FIXTURES / "not_simulation.py") is False

    def test_detect_missing_file(self):
        assert self.driver.detect(Path("/does/not/exist.sif")) is False


class TestLint:
    def setup_method(self):
        self.driver = ElmerDriver()

    def test_lint_good_sif(self):
        r = self.driver.lint(FIXTURES / "elmer_good.sif")
        assert r.ok is True

    def test_lint_missing_simulation_is_error(self):
        r = self.driver.lint(FIXTURES / "elmer_no_simulation.sif")
        assert r.ok is False
        assert any(d.level == "error" and "simulation" in d.message.lower()
                   for d in r.diagnostics)

    def test_lint_no_solver_is_warning(self):
        r = self.driver.lint(FIXTURES / "elmer_no_solver.sif")
        assert r.ok is True
        assert any(d.level == "warning" and "solver" in d.message.lower()
                   for d in r.diagnostics)

    def test_lint_unsupported_suffix(self):
        r = self.driver.lint(FIXTURES / "not_simulation.py")
        assert r.ok is False


class TestConnect:
    def test_connect_not_installed(self, monkeypatch):
        driver = ElmerDriver()
        monkeypatch.setattr(driver, "detect_installed", lambda: [])
        info = driver.connect()
        assert info.status == "not_installed"

    def test_connect_found(self, monkeypatch):
        from sim.driver import SolverInstall
        driver = ElmerDriver()
        monkeypatch.setattr(
            driver, "detect_installed",
            lambda: [SolverInstall(
                name="elmer", version="26.1",
                path="/data/Chenyx/sim/opt/elmer/bin",
                source="test",
                extra={"bin": "/data/Chenyx/sim/opt/elmer/bin/ElmerSolver"},
            )],
        )
        info = driver.connect()
        assert info.status == "ok"


class TestParseOutput:
    def setup_method(self):
        self.driver = ElmerDriver()

    def test_last_json_line(self):
        stdout = 'ELMER SOLVER FINISHED AT:\n{"max_temp": 0.0736}\n'
        assert self.driver.parse_output(stdout) == {"max_temp": 0.0736}

    def test_no_json(self):
        assert self.driver.parse_output("ELMER SOLVER FINISHED") == {}


class TestRunFile:
    def test_raises_when_not_installed(self, monkeypatch):
        driver = ElmerDriver()
        monkeypatch.setattr(driver, "detect_installed", lambda: [])
        with pytest.raises(RuntimeError, match="(?i)elmer"):
            driver.run_file(FIXTURES / "elmer_good.sif")

    def test_rejects_unsupported_suffix(self, monkeypatch):
        from sim.driver import SolverInstall
        driver = ElmerDriver()
        monkeypatch.setattr(
            driver, "detect_installed",
            lambda: [SolverInstall(
                name="elmer", version="26.1", path="/x", source="test",
                extra={"bin": "/x/ElmerSolver"},
            )],
        )
        with pytest.raises(RuntimeError, match="(?i)elmer"):
            driver.run_file(FIXTURES / "not_simulation.py")
