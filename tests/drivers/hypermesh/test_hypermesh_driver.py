"""Tier 1 protocol-compliance tests for the HyperMesh driver."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from sim.drivers.hypermesh import HyperMeshDriver

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"


class TestDetect:
    def setup_method(self):
        self.driver = HyperMeshDriver()

    def test_detect_good(self):
        assert self.driver.detect(FIXTURES / "hypermesh_good.py") is True

    def test_detect_no_import(self):
        assert self.driver.detect(FIXTURES / "hypermesh_no_import.py") is False

    def test_detect_not_python(self):
        assert self.driver.detect(FIXTURES / "not_simulation.py") is False

    def test_detect_missing(self):
        assert self.driver.detect(Path("/no/such/file.py")) is False

    def test_detect_no_usage_still_detected(self):
        assert self.driver.detect(FIXTURES / "hypermesh_no_usage.py") is True

    def test_detect_wrong_extension(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w") as f:
            f.write("import hm\n")
            p = Path(f.name)
        try:
            assert self.driver.detect(p) is False
        finally:
            os.unlink(p)

    def test_detect_from_hm(self):
        """Scripts with 'from hm.entities' are detected."""
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w") as f:
            f.write("from hm.entities import Node\n")
            p = Path(f.name)
        try:
            assert self.driver.detect(p) is True
        finally:
            os.unlink(p)


class TestLint:
    def setup_method(self):
        self.driver = HyperMeshDriver()

    def test_lint_good(self):
        r = self.driver.lint(FIXTURES / "hypermesh_good.py")
        assert r.ok is True

    def test_lint_no_import_is_error(self):
        r = self.driver.lint(FIXTURES / "hypermesh_no_import.py")
        assert r.ok is False
        assert any("import hm" in d.message for d in r.diagnostics)

    def test_lint_no_usage_is_warning(self):
        r = self.driver.lint(FIXTURES / "hypermesh_no_usage.py")
        assert r.ok is True
        assert any(d.level == "warning" for d in r.diagnostics)

    def test_lint_syntax_error(self):
        r = self.driver.lint(FIXTURES / "hypermesh_syntax_error.py")
        assert r.ok is False
        assert any("yntax" in d.message for d in r.diagnostics)

    def test_lint_gui_warning(self):
        r = self.driver.lint(FIXTURES / "hypermesh_gui.py")
        assert r.ok is True
        assert any("InteractiveSelection" in d.message for d in r.diagnostics)

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
        with tempfile.NamedTemporaryFile(suffix=".tcl", delete=False) as f:
            p = Path(f.name)
        try:
            r = self.driver.lint(p)
            assert r.ok is False
        finally:
            os.unlink(p)


class TestConnect:
    def test_not_installed(self, monkeypatch):
        d = HyperMeshDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [])
        info = d.connect()
        assert info.status == "not_installed"

    def test_found(self, monkeypatch):
        from sim.driver import SolverInstall
        d = HyperMeshDriver()
        monkeypatch.setattr(
            d, "detect_installed",
            lambda: [SolverInstall(
                name="hypermesh", version="2025",
                path=r"C:\Altair\2025\hwdesktop\hw\bin\win64",
                source="test",
                extra={"hw_exe": r"C:\Altair\2025\hwdesktop\hw\bin\win64\hw.exe",
                       "raw_version": "2025.1.0"},
            )],
        )
        info = d.connect()
        assert info.status == "ok"
        assert info.version == "2025"


class TestParseOutput:
    def setup_method(self):
        self.driver = HyperMeshDriver()

    def test_last_json(self):
        stdout = 'loading...\n{"ok": true, "n_nodes": 5000}\n'
        result = self.driver.parse_output(stdout)
        assert result["ok"] is True
        assert result["n_nodes"] == 5000

    def test_no_json(self):
        assert self.driver.parse_output("no json here") == {}

    def test_empty(self):
        assert self.driver.parse_output("") == {}

    def test_multi_json_last_wins(self):
        stdout = '{"first": 1}\nstuff\n{"second": 2}\n'
        result = self.driver.parse_output(stdout)
        assert "second" in result

    def test_broken_json_skipped(self):
        stdout = '{"broken\n{"ok": true}\n'
        result = self.driver.parse_output(stdout)
        assert result["ok"] is True


class TestRunFile:
    def test_raises_when_not_installed(self, monkeypatch):
        d = HyperMeshDriver()
        monkeypatch.setattr(d, "detect_installed", lambda: [])
        with pytest.raises(RuntimeError, match="(?i)hypermesh"):
            d.run_file(FIXTURES / "hypermesh_good.py")

    def test_rejects_unsupported_suffix(self, monkeypatch):
        from sim.driver import SolverInstall
        d = HyperMeshDriver()
        monkeypatch.setattr(
            d, "detect_installed",
            lambda: [SolverInstall(
                name="hypermesh", version="2025", path="/opt",
                source="test",
                extra={"hw_exe": "/opt/hw"},
            )],
        )
        with tempfile.NamedTemporaryFile(suffix=".tcl", delete=False) as f:
            p = Path(f.name)
        try:
            with pytest.raises(RuntimeError, match=r"\.py"):
                d.run_file(p)
        finally:
            os.unlink(p)


class TestDetectInstalled:
    def test_empty_when_nothing_found(self, monkeypatch):
        d = HyperMeshDriver()
        monkeypatch.setattr("shutil.which", lambda _: None)
        monkeypatch.setattr(
            "sim.drivers.hypermesh.driver._scan_altair_installs",
            lambda: [],
        )
        assert d.detect_installed() == []


class TestProperties:
    def test_name(self):
        assert HyperMeshDriver().name == "hypermesh"

    def test_supports_session(self):
        assert HyperMeshDriver().supports_session is False
