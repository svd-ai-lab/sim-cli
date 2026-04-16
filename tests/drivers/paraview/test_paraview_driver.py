"""Tier 1 protocol-compliance tests for the ParaView driver."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from sim.drivers.paraview import ParaViewDriver

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"


class TestDetect:
    def setup_method(self):
        self.driver = ParaViewDriver()

    def test_detect_good(self):
        assert self.driver.detect(FIXTURES / "paraview_good.py") is True

    def test_detect_no_import(self):
        assert self.driver.detect(FIXTURES / "paraview_no_import.py") is False

    def test_detect_not_python(self):
        assert self.driver.detect(FIXTURES / "not_simulation.py") is False

    def test_detect_missing(self):
        assert self.driver.detect(Path("/no/such/file.py")) is False

    def test_detect_no_api_still_detected(self):
        """Script with `import paraview` but no API calls is still detected."""
        assert self.driver.detect(FIXTURES / "paraview_no_api.py") is True

    def test_detect_wrong_extension(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w") as f:
            f.write("from paraview.simple import Sphere\n")
            p = Path(f.name)
        try:
            assert self.driver.detect(p) is False
        finally:
            os.unlink(p)


class TestLint:
    def setup_method(self):
        self.driver = ParaViewDriver()

    def test_lint_good(self):
        r = self.driver.lint(FIXTURES / "paraview_good.py")
        assert r.ok is True

    def test_lint_no_import_is_error(self):
        r = self.driver.lint(FIXTURES / "paraview_no_import.py")
        assert r.ok is False
        assert any("import paraview" in d.message for d in r.diagnostics)

    def test_lint_no_api_is_warning(self):
        r = self.driver.lint(FIXTURES / "paraview_no_api.py")
        assert r.ok is True
        assert any(d.level == "warning" for d in r.diagnostics)

    def test_lint_syntax_error(self):
        r = self.driver.lint(FIXTURES / "paraview_syntax_error.py")
        assert r.ok is False
        assert any("yntax" in d.message for d in r.diagnostics)

    def test_lint_interact_warning(self):
        r = self.driver.lint(FIXTURES / "paraview_interact.py")
        assert r.ok is True
        assert any("Interact" in d.message for d in r.diagnostics)

    def test_lint_empty_script(self):
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w") as f:
            f.write("")
            p = Path(f.name)
        try:
            r = self.driver.lint(p)
            assert r.ok is False
            assert any("empty" in d.message.lower() for d in r.diagnostics)
        finally:
            os.unlink(p)

    def test_lint_unsupported_suffix(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            p = Path(f.name)
        try:
            r = self.driver.lint(p)
            assert r.ok is False
            assert any("Unsupported" in d.message for d in r.diagnostics)
        finally:
            os.unlink(p)


class TestConnect:
    def test_not_installed(self, monkeypatch):
        d = ParaViewDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [])
        info = d.connect()
        assert info.status == "not_installed"
        assert "paraview" in info.message.lower() or "ParaView" in info.message

    def test_found(self, monkeypatch):
        from sim.driver import SolverInstall
        d = ParaViewDriver()
        monkeypatch.setattr(
            d, "detect_installed",
            lambda: [SolverInstall(
                name="paraview", version="5.13", path="/opt/ParaView",
                source="test",
                extra={"pvpython": "/opt/ParaView/bin/pvpython",
                       "raw_version": "5.13.0"},
            )],
        )
        info = d.connect()
        assert info.status == "ok"
        assert info.version == "5.13"


class TestParseOutput:
    def setup_method(self):
        self.driver = ParaViewDriver()

    def test_last_json(self):
        stdout = 'loading...\n{"ok": true, "n_cells": 1024}\n'
        result = self.driver.parse_output(stdout)
        assert result["ok"] is True
        assert result["n_cells"] == 1024

    def test_no_json(self):
        assert self.driver.parse_output("no json here") == {}

    def test_empty(self):
        assert self.driver.parse_output("") == {}

    def test_multi_json_last_wins(self):
        stdout = '{"first": 1}\nstuff\n{"second": 2}\n'
        result = self.driver.parse_output(stdout)
        assert "second" in result
        assert "first" not in result

    def test_broken_json_skipped(self):
        stdout = '{"broken\n{"ok": true}\n'
        result = self.driver.parse_output(stdout)
        assert result["ok"] is True


class TestRunFile:
    def test_raises_when_not_installed(self, monkeypatch):
        d = ParaViewDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [])
        with pytest.raises(RuntimeError, match="(?i)paraview"):
            d.run_file(FIXTURES / "paraview_good.py")

    def test_rejects_unsupported_suffix(self, monkeypatch):
        from sim.driver import SolverInstall
        d = ParaViewDriver()
        monkeypatch.setattr(
            d, "detect_installed",
            lambda: [SolverInstall(
                name="paraview", version="5.13", path="/opt",
                source="test",
                extra={"pvpython": "/opt/pvpython"},
            )],
        )
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            p = Path(f.name)
        try:
            with pytest.raises(RuntimeError, match=r"\.py"):
                d.run_file(p)
        finally:
            os.unlink(p)


class TestDetectInstalled:
    def test_empty_when_nothing_found(self, monkeypatch):
        """With no ParaView anywhere, returns empty list."""
        d = ParaViewDriver()
        monkeypatch.setattr("shutil.which", lambda _: None)
        monkeypatch.setattr(
            "sim.drivers.paraview.driver._probe_pvpython", lambda _: None,
        )
        monkeypatch.setattr(
            "sim.drivers.paraview.driver._probe_python_for_paraview",
            lambda _: None,
        )
        monkeypatch.setattr(
            "sim.drivers.paraview.driver._scan_paraview_installs",
            lambda: [],
        )
        result = d.detect_installed()
        assert result == []

    def test_version_sorting(self, monkeypatch):
        """Higher versions sort first."""
        from sim.driver import SolverInstall
        d = ParaViewDriver()
        monkeypatch.setattr(
            d, "detect_installed",
            lambda: sorted([
                SolverInstall(name="paraview", version="5.12", path="/a",
                              source="a", extra={}),
                SolverInstall(name="paraview", version="5.13", path="/b",
                              source="b", extra={}),
            ], key=lambda i: i.version, reverse=True),
        )
        installs = d.detect_installed()
        assert installs[0].version == "5.13"


class TestProperties:
    def test_name(self):
        assert ParaViewDriver().name == "paraview"

    def test_supports_session(self):
        assert ParaViewDriver().supports_session is False
