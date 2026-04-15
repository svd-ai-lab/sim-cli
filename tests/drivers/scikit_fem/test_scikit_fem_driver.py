"""Tier 1 protocol-compliance tests for the scikit-fem driver."""
from __future__ import annotations

from pathlib import Path

import pytest

from sim.drivers.scikit_fem import ScikitFemDriver

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"


class TestDetect:
    def setup_method(self):
        self.driver = ScikitFemDriver()

    def test_detect_good_py(self):
        assert self.driver.detect(FIXTURES / "skfem_good.py") is True

    def test_detect_no_import(self):
        assert self.driver.detect(FIXTURES / "skfem_no_import.py") is False

    def test_detect_unsupported_suffix(self):
        assert self.driver.detect(FIXTURES / "not_simulation.py") is False

    def test_detect_syntax_error_still_detects(self):
        assert self.driver.detect(FIXTURES / "skfem_syntax_error.py") is True

    def test_detect_missing_file(self):
        assert self.driver.detect(Path("/does/not/exist.py")) is False


class TestLint:
    def setup_method(self):
        self.driver = ScikitFemDriver()

    def test_lint_good_py(self):
        r = self.driver.lint(FIXTURES / "skfem_good.py")
        assert r.ok is True

    def test_lint_no_import_is_error(self):
        r = self.driver.lint(FIXTURES / "skfem_no_import.py")
        assert r.ok is False
        assert any(d.level == "error" and "import" in d.message.lower()
                   for d in r.diagnostics)

    def test_lint_no_solve_is_warning(self):
        r = self.driver.lint(FIXTURES / "skfem_no_solve.py")
        assert r.ok is True  # warnings don't fail
        assert any(d.level == "warning" for d in r.diagnostics)

    def test_lint_syntax_error_is_error(self):
        r = self.driver.lint(FIXTURES / "skfem_syntax_error.py")
        assert r.ok is False
        assert any(d.level == "error" and "syntax" in d.message.lower()
                   for d in r.diagnostics)

    def test_lint_unsupported_suffix(self):
        from tempfile import NamedTemporaryFile
        import os
        with NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"hello")
            p = Path(f.name)
        try:
            r = self.driver.lint(p)
            assert r.ok is False
        finally:
            os.unlink(p)


class TestConnect:
    def test_connect_not_installed(self, monkeypatch):
        driver = ScikitFemDriver()
        monkeypatch.setattr(driver, "detect_installed", lambda: [])
        info = driver.connect()
        assert info.status == "not_installed"

    def test_connect_found(self, monkeypatch):
        from sim.driver import SolverInstall
        driver = ScikitFemDriver()
        monkeypatch.setattr(
            driver, "detect_installed",
            lambda: [SolverInstall(
                name="scikit_fem", version="12.0",
                path="/fake/bin", source="test",
                extra={"python": "/fake/bin/python", "raw_version": "12.0.1"},
            )],
        )
        info = driver.connect()
        assert info.status == "ok"
        assert info.version is not None


class TestParseOutput:
    def setup_method(self):
        self.driver = ScikitFemDriver()

    def test_last_json_line(self):
        stdout = 'Info: done\n{"u_max": 0.0734, "nodes": 289}\n'
        assert self.driver.parse_output(stdout) == {"u_max": 0.0734, "nodes": 289}

    def test_no_json(self):
        assert self.driver.parse_output("nothing") == {}


class TestRunFile:
    def test_raises_when_not_installed(self, monkeypatch):
        driver = ScikitFemDriver()
        monkeypatch.setattr(driver, "detect_installed", lambda: [])
        with pytest.raises(RuntimeError, match="(?i)scikit"):
            driver.run_file(FIXTURES / "skfem_good.py")

    def test_rejects_unsupported_suffix(self, monkeypatch):
        from sim.driver import SolverInstall
        driver = ScikitFemDriver()
        monkeypatch.setattr(
            driver, "detect_installed",
            lambda: [SolverInstall(
                name="scikit_fem", version="12.0", path="/x", source="test",
                extra={"python": "/x/python"},
            )],
        )
        from tempfile import NamedTemporaryFile
        import os
        with NamedTemporaryFile(suffix=".txt", delete=False) as f:
            p = Path(f.name)
        try:
            with pytest.raises(RuntimeError, match="(?i)scikit"):
                driver.run_file(p)
        finally:
            os.unlink(p)
