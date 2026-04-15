"""Tier 1 protocol-compliance tests for the SU2 driver."""
from __future__ import annotations

from pathlib import Path

import pytest

from sim.drivers.su2 import Su2Driver

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"


class TestDetect:
    def setup_method(self):
        self.driver = Su2Driver()

    def test_detect_good_cfg(self):
        assert self.driver.detect(FIXTURES / "su2_good.cfg") is True

    def test_detect_cfg_without_su2_keywords(self):
        assert self.driver.detect(FIXTURES / "su2_not_cfg.cfg") is False

    def test_detect_non_cfg_file(self):
        assert self.driver.detect(FIXTURES / "not_simulation.py") is False

    def test_detect_missing_file(self):
        assert self.driver.detect(Path("/does/not/exist.cfg")) is False


class TestLint:
    def setup_method(self):
        self.driver = Su2Driver()

    def test_lint_good_cfg(self):
        r = self.driver.lint(FIXTURES / "su2_good.cfg")
        assert r.ok is True
        assert len([d for d in r.diagnostics if d.level == "error"]) == 0

    def test_lint_missing_solver_is_error(self):
        r = self.driver.lint(FIXTURES / "su2_no_solver.cfg")
        assert r.ok is False
        assert any(
            d.level == "error" and "solver" in d.message.lower()
            for d in r.diagnostics
        )

    def test_lint_no_markers_is_warning(self):
        r = self.driver.lint(FIXTURES / "su2_no_markers.cfg")
        # warnings don't fail lint
        assert r.ok is True
        assert any(d.level == "warning" for d in r.diagnostics)

    def test_lint_unsupported_suffix(self):
        r = self.driver.lint(FIXTURES / "not_simulation.py")
        assert r.ok is False


class TestConnect:
    def test_connect_not_installed(self, monkeypatch):
        driver = Su2Driver()
        monkeypatch.setattr(driver, "detect_installed", lambda: [])
        info = driver.connect()
        assert info.status == "not_installed"

    def test_connect_found(self, monkeypatch):
        from sim.driver import SolverInstall
        driver = Su2Driver()
        monkeypatch.setattr(
            driver, "detect_installed",
            lambda: [SolverInstall(
                name="su2", version="8.4",
                path="/data/Chenyx/sim/opt/su2/bin",
                source="test",
                extra={"bin": "/data/Chenyx/sim/opt/su2/bin/SU2_CFD"},
            )],
        )
        info = driver.connect()
        assert info.status == "ok"
        assert info.version is not None


class TestParseOutput:
    def setup_method(self):
        self.driver = Su2Driver()

    def test_last_json_line(self):
        stdout = 'Exit Success\n{"rms_rho_final": -4.22, "iters": 200}\n'
        assert self.driver.parse_output(stdout) == {
            "rms_rho_final": -4.22, "iters": 200,
        }

    def test_no_json(self):
        assert self.driver.parse_output("Exit Success (SU2_CFD)") == {}


class TestRunFile:
    def test_raises_when_not_installed(self, monkeypatch):
        driver = Su2Driver()
        monkeypatch.setattr(driver, "detect_installed", lambda: [])
        with pytest.raises(RuntimeError, match="(?i)su2"):
            driver.run_file(FIXTURES / "su2_good.cfg")

    def test_rejects_unsupported_suffix(self, monkeypatch):
        from sim.driver import SolverInstall
        driver = Su2Driver()
        monkeypatch.setattr(
            driver, "detect_installed",
            lambda: [SolverInstall(
                name="su2", version="8.4", path="/x", source="test",
                extra={"bin": "/x/SU2_CFD"},
            )],
        )
        with pytest.raises(RuntimeError, match="(?i)su2"):
            driver.run_file(FIXTURES / "not_simulation.py")
