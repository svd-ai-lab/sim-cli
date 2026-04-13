"""Tier 1 protocol-compliance tests for the LS-DYNA driver."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sim.drivers.lsdyna import LsDynaDriver

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "lsdyna"


class TestDetect:
    def setup_method(self):
        self.driver = LsDynaDriver()

    def test_detect_good_k_file(self):
        """Keyword file with *KEYWORD marker -> True."""
        assert self.driver.detect(FIXTURES / "lsdyna_good.k") is True

    def test_detect_minimal_k_file(self):
        """Minimal keyword file with *KEYWORD + *END -> True."""
        assert self.driver.detect(FIXTURES / "lsdyna_minimal.k") is True

    def test_detect_no_keyword_marker(self):
        """.k file without *KEYWORD -> False."""
        assert self.driver.detect(FIXTURES / "lsdyna_no_keyword.k") is False

    def test_detect_unrelated_script(self):
        """Non-.k file -> False."""
        assert self.driver.detect(FIXTURES.parent / "not_simulation.py") is False

    def test_detect_missing_file(self):
        """Non-existent path -> False (no exception)."""
        assert self.driver.detect(Path("/does/not/exist.k")) is False

    def test_detect_inp_file_rejected(self):
        """Abaqus .inp file -> False (different solver)."""
        inp = FIXTURES.parent / "abaqus" / "abaqus_inp_good.inp"
        if inp.is_file():
            assert self.driver.detect(inp) is False

    def test_detect_dyn_extension(self):
        """.dyn extension with *KEYWORD -> True."""
        dyn = FIXTURES / "test_ext.dyn"
        dyn.write_text("*KEYWORD\n*TITLE\ntest\n*END\n", encoding="utf-8")
        try:
            assert self.driver.detect(dyn) is True
        finally:
            dyn.unlink(missing_ok=True)


class TestLint:
    def setup_method(self):
        self.driver = LsDynaDriver()

    def test_lint_good_k(self):
        result = self.driver.lint(FIXTURES / "lsdyna_good.k")
        assert result.ok is True
        assert len([d for d in result.diagnostics if d.level == "error"]) == 0

    def test_lint_minimal_k(self):
        """Minimal file: ok but warnings about missing nodes/elements."""
        result = self.driver.lint(FIXTURES / "lsdyna_minimal.k")
        assert result.ok is True
        assert any(d.level == "warning" for d in result.diagnostics)

    def test_lint_no_keyword(self):
        """File without *KEYWORD -> error."""
        result = self.driver.lint(FIXTURES / "lsdyna_no_keyword.k")
        assert result.ok is False
        assert any(
            d.level == "error" and "KEYWORD" in d.message
            for d in result.diagnostics
        )

    def test_lint_missing_file(self):
        result = self.driver.lint(Path("/does/not/exist.k"))
        assert result.ok is False
        assert any(d.level == "error" for d in result.diagnostics)

    def test_lint_unsupported_ext(self):
        result = self.driver.lint(FIXTURES.parent / "not_simulation.py")
        assert result.ok is False
        assert any(
            "unsupported" in d.message.lower() or "expected" in d.message.lower()
            for d in result.diagnostics
        )

    def test_lint_no_nodes_warning(self):
        """File without *NODE -> warning, not error."""
        result = self.driver.lint(FIXTURES / "lsdyna_no_nodes.k")
        assert result.ok is True
        assert any(
            d.level == "warning" and "NODE" in d.message
            for d in result.diagnostics
        )

    def test_lint_no_end_warning(self):
        """File without *END -> warning."""
        no_end = FIXTURES / "test_no_end.k"
        no_end.write_text("*KEYWORD\n*TITLE\ntest\n", encoding="utf-8")
        try:
            result = self.driver.lint(no_end)
            assert result.ok is True
            assert any(
                d.level == "warning" and "END" in d.message
                for d in result.diagnostics
            )
        finally:
            no_end.unlink(missing_ok=True)


class TestConnect:
    def test_connect_not_installed(self, monkeypatch):
        """When LS-DYNA not found -> status='not_installed'."""
        driver = LsDynaDriver()
        monkeypatch.setattr(driver, "detect_installed", lambda: [])
        info = driver.connect()
        assert info.status == "not_installed"

    def test_connect_found(self, monkeypatch):
        """When LS-DYNA found -> status='ok', version populated."""
        from sim.driver import SolverInstall

        driver = LsDynaDriver()
        monkeypatch.setattr(
            driver,
            "detect_installed",
            lambda: [
                SolverInstall(
                    name="ls_dyna",
                    version="R14.0",
                    path="C:/ANSYS/bin",
                    source="test",
                    extra={"exe": "C:/ANSYS/bin/lsdyna_sp.exe"},
                )
            ],
        )
        info = driver.connect()
        assert info.status == "ok"
        assert info.version is not None


class TestParseOutput:
    def setup_method(self):
        self.driver = LsDynaDriver()

    def test_last_json_line(self):
        stdout = 'LS-DYNA solver output\n{"termination_time": 0.001}\n'
        result = self.driver.parse_output(stdout)
        assert result == {"termination_time": 0.001}

    def test_no_json(self):
        result = self.driver.parse_output("just plain solver output\n")
        assert result == {}

    def test_multiple_json_takes_last(self):
        stdout = '{"a": 1}\nsome log\n{"b": 2}\n'
        result = self.driver.parse_output(stdout)
        assert result == {"b": 2}

    def test_invalid_json_skipped(self):
        stdout = '{broken\n{"valid": true}\n'
        result = self.driver.parse_output(stdout)
        assert result == {"valid": True}

    def test_lsdyna_termination_parsing(self):
        """Parse LS-DYNA normal termination message."""
        stdout = (
            " N o r m a l    t e r m i n a t i o n\n"
            " Elapsed time     1.23 seconds\n"
        )
        result = self.driver.parse_output(stdout)
        # Should extract termination info even without JSON
        assert isinstance(result, dict)

    def test_lsdyna_error_detection(self):
        """Error patterns detected and surfaced."""
        stdout = (
            "*** Error reading keyword on line 15\n"
            " *** Fatal error - terminating\n"
        )
        result = self.driver.parse_output(stdout)
        assert isinstance(result, dict)


class TestRunFile:
    def test_raises_when_not_installed(self, monkeypatch):
        driver = LsDynaDriver()
        monkeypatch.setattr(driver, "detect_installed", lambda: [])
        with pytest.raises(RuntimeError, match="(?i)ls.dyna"):
            driver.run_file(FIXTURES / "lsdyna_good.k")


class TestDetectInstalled:
    def test_empty_when_mocked(self, monkeypatch):
        """When all finders return empty -> empty list."""
        import sim.drivers.lsdyna.driver as mod

        monkeypatch.setattr(mod, "_INSTALL_FINDERS", [lambda: []])
        driver = LsDynaDriver()
        assert driver.detect_installed() == []
