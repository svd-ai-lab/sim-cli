"""Tests for the COMSOL driver — all pass without COMSOL installed."""
from pathlib import Path

from sim.drivers.comsol.driver import ComsolDriver

FIXTURES = Path(__file__).parent / "fixtures"


class TestDetect:
    def setup_method(self):
        self.driver = ComsolDriver()

    def test_detect_mph_import(self):
        assert self.driver.detect(FIXTURES / "comsol_good.py") is True

    def test_detect_no_import(self):
        assert self.driver.detect(FIXTURES / "mock_solver.py") is False

    def test_detect_from_import(self, tmp_path):
        script = tmp_path / "test.py"
        script.write_text("from mph import Client\nclient = Client()\n")
        assert self.driver.detect(script) is True


class TestLint:
    def setup_method(self):
        self.driver = ComsolDriver()

    def test_lint_good_script(self):
        result = self.driver.lint(FIXTURES / "comsol_good.py")
        assert result.ok is True

    def test_lint_no_import(self):
        result = self.driver.lint(FIXTURES / "comsol_no_import.py")
        assert result.ok is False
        assert any("does not import" in d.message for d in result.diagnostics)

    def test_lint_no_client(self):
        result = self.driver.lint(FIXTURES / "comsol_no_client.py")
        assert result.ok is True
        assert any("no mph.client" in d.message.lower() for d in result.diagnostics)

    def test_lint_syntax_error(self, tmp_path):
        script = tmp_path / "bad.py"
        script.write_text("import mph\ndef foo(\n")
        result = self.driver.lint(script)
        assert result.ok is False
        assert any("syntax" in d.message.lower() for d in result.diagnostics)


class TestConnect:
    def test_connect_not_installed(self, monkeypatch):
        monkeypatch.setattr(
            "builtins.__import__",
            _make_import_blocker("mph"),
        )
        driver = ComsolDriver()
        info = driver.connect()
        assert info.status == "not_installed"
        assert info.solver == "comsol"


class TestParseOutput:
    def setup_method(self):
        self.driver = ComsolDriver()

    def test_parse_json_line(self):
        stdout = 'Loading model...\n{"capacitance_F": 1.23e-12, "model": "capacitor"}'
        result = self.driver.parse_output(stdout)
        assert result["capacitance_F"] == 1.23e-12
        assert result["model"] == "capacitor"

    def test_parse_empty(self):
        assert self.driver.parse_output("") == {}

    def test_parse_no_json(self):
        assert self.driver.parse_output("some plain text\n") == {}

    def test_parse_last_json_wins(self):
        stdout = '{"a": 1}\n{"b": 2}'
        result = self.driver.parse_output(stdout)
        assert result == {"b": 2}


class TestRunFile:
    def test_run_constructs_command(self, monkeypatch, tmp_path):
        """Verify run_file uses execute_script correctly."""
        script = tmp_path / "test.py"
        script.write_text("import mph\nclient = mph.start()\n")

        from sim import runner
        from sim.driver import RunResult

        captured = {}

        def fake_execute(s, python=None, solver="unknown"):
            captured["script"] = s
            captured["solver"] = solver
            return RunResult(
                exit_code=0,
                stdout="{}",
                stderr="",
                duration_s=0.1,
                script=str(s),
                solver=solver,
                timestamp="2026-01-01T00:00:00+00:00",
            )

        monkeypatch.setattr(runner, "execute_script", fake_execute)

        result = runner.execute_script(script, solver="comsol")
        assert captured["solver"] == "comsol"
        assert captured["script"] == script


def _make_import_blocker(blocked: str):
    """Return an __import__ replacement that blocks a specific module."""
    import builtins

    real_import = builtins.__import__

    def blocker(name, *args, **kwargs):
        if name == blocked or name.startswith(blocked + "."):
            raise ImportError(f"Mocked: {name} not installed")
        return real_import(name, *args, **kwargs)

    return blocker
