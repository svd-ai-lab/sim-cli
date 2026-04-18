"""Newton driver unit tests — no real newton install required."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sim.drivers import get_driver
from sim.drivers.newton import NewtonDriver

FIX = Path(__file__).parent.parent.parent / "fixtures" / "newton"


@pytest.fixture
def driver() -> NewtonDriver:
    return NewtonDriver()


class TestRegistration:
    def test_registered(self):
        d = get_driver("newton")
        assert d is not None
        assert d.name == "newton"
        assert d.supports_session is False

    def test_is_instance(self):
        assert isinstance(get_driver("newton"), NewtonDriver)


class TestDetect:
    def test_detects_recipe_json_new_schema(self, driver, tmp_path):
        p = tmp_path / "r.json"
        p.write_text(json.dumps({
            "schema": "sim/newton/recipe/v1",
            "ops": [{"op": "add_ground_plane", "args": {}}],
        }))
        assert driver.detect(p) is True

    def test_detects_recipe_json_legacy_schema(self, driver, tmp_path):
        p = tmp_path / "r.json"
        p.write_text(json.dumps({
            "schema": "newton-cli/recipe/v1",
            "ops": [],
        }))
        assert driver.detect(p) is True

    def test_rejects_non_recipe_json(self, driver, tmp_path):
        p = tmp_path / "r.json"
        p.write_text(json.dumps({"schema": "other/v1"}))
        assert driver.detect(p) is False

    def test_rejects_malformed_json(self, driver, tmp_path):
        p = tmp_path / "r.json"
        p.write_text("{not json")
        assert driver.detect(p) is False

    def test_detects_py_newton_import(self, driver, tmp_path):
        p = tmp_path / "s.py"
        p.write_text("import newton\nprint('hi')\n")
        assert driver.detect(p) is True

    def test_detects_py_warp_import(self, driver, tmp_path):
        p = tmp_path / "s.py"
        p.write_text("import warp as wp\n")
        assert driver.detect(p) is True

    def test_detects_py_solver_class(self, driver, tmp_path):
        p = tmp_path / "s.py"
        p.write_text("from newton.solvers import SolverXPBD\nsolver = SolverXPBD(model)\n")
        assert driver.detect(p) is True

    def test_rejects_plain_python(self, driver, tmp_path):
        p = tmp_path / "s.py"
        p.write_text("print('hello')\n")
        assert driver.detect(p) is False

    def test_rejects_unknown_suffix(self, driver, tmp_path):
        p = tmp_path / "s.txt"
        p.write_text("import newton")
        assert driver.detect(p) is False

    def test_rejects_missing_file(self, driver, tmp_path):
        assert driver.detect(tmp_path / "nope.py") is False


class TestLintRecipe:
    def test_valid_recipe(self, driver, tmp_path):
        p = tmp_path / "r.json"
        p.write_text(json.dumps({
            "schema": "sim/newton/recipe/v1",
            "ops": [{"op": "add_ground_plane", "args": {}}],
        }))
        r = driver.lint(p)
        assert r.ok is True

    def test_bad_schema(self, driver, tmp_path):
        p = tmp_path / "r.json"
        p.write_text(json.dumps({"schema": "other/v1", "ops": []}))
        r = driver.lint(p)
        assert r.ok is False
        assert any("schema" in d.message.lower() for d in r.diagnostics)

    def test_missing_ops(self, driver, tmp_path):
        p = tmp_path / "r.json"
        p.write_text(json.dumps({"schema": "sim/newton/recipe/v1"}))
        r = driver.lint(p)
        assert r.ok is False

    def test_bad_op_shape(self, driver, tmp_path):
        p = tmp_path / "r.json"
        p.write_text(json.dumps({
            "schema": "sim/newton/recipe/v1",
            "ops": [{"args": {}}],  # missing "op"
        }))
        r = driver.lint(p)
        assert r.ok is False

    def test_malformed_json(self, driver, tmp_path):
        p = tmp_path / "r.json"
        p.write_text("{invalid")
        r = driver.lint(p)
        assert r.ok is False


class TestLintPy:
    def test_valid_py(self, driver, tmp_path):
        p = tmp_path / "s.py"
        p.write_text("import newton\nprint('hi')\n")
        r = driver.lint(p)
        assert r.ok is True

    def test_syntax_error(self, driver, tmp_path):
        p = tmp_path / "s.py"
        p.write_text("import newton\ndef broken(:\n")
        r = driver.lint(p)
        assert r.ok is False
        assert any(d.level == "error" for d in r.diagnostics)

    def test_private_import_warning(self, driver, tmp_path):
        p = tmp_path / "s.py"
        p.write_text("from newton._src.internal import thing\n")
        r = driver.lint(p)
        assert r.ok is True  # warning only
        assert any(d.level == "warning" and "_src" in d.message for d in r.diagnostics)

    def test_unsupported_suffix(self, driver, tmp_path):
        p = tmp_path / "s.cpp"
        p.write_text("int main() {}")
        r = driver.lint(p)
        assert r.ok is False

    def test_empty_file(self, driver, tmp_path):
        p = tmp_path / "s.py"
        p.write_text("")
        r = driver.lint(p)
        assert r.ok is False


class TestParseOutput:
    def test_extracts_envelope(self, driver):
        stdout = (
            "some Warp banner\n"
            'intermediate log\n'
            '{"schema":"sim/newton/v1","data":{"state_path":"/tmp/a.npz","num_frames":10}}\n'
        )
        out = driver.parse_output(stdout)
        assert out == {"state_path": "/tmp/a.npz", "num_frames": 10}

    def test_ignores_other_schemas(self, driver):
        stdout = '{"schema":"other/v1","data":{"x":1}}\n'
        assert driver.parse_output(stdout) == {}

    def test_empty_stdout(self, driver):
        assert driver.parse_output("") == {}

    def test_picks_last_envelope_when_multiple(self, driver):
        stdout = (
            '{"schema":"sim/newton/v1","data":{"x":1}}\n'
            '{"schema":"sim/newton/v1","data":{"x":2}}\n'
        )
        assert driver.parse_output(stdout) == {"x": 2}


class TestConnectNotInstalled:
    def test_connect_reports_missing(self, driver, monkeypatch):
        monkeypatch.setattr(driver, "detect_installed", lambda: [])
        info = driver.connect()
        assert info.status == "not_installed"
        assert info.version is None
        assert "newton" in info.message.lower()

    def test_run_file_raises_when_missing(self, driver, tmp_path, monkeypatch):
        monkeypatch.setattr(driver, "detect_installed", lambda: [])
        p = tmp_path / "r.json"
        p.write_text(json.dumps({"schema": "sim/newton/recipe/v1", "ops": []}))
        with pytest.raises(RuntimeError, match="not installed"):
            driver.run_file(p)

    def test_run_file_rejects_unknown_suffix(self, driver, tmp_path):
        p = tmp_path / "foo.txt"
        p.write_text("x")
        with pytest.raises(RuntimeError, match="only accepts"):
            driver.run_file(p)
