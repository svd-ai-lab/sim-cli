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
        # M1: connect() no longer imports mph; it reports based on
        # _scan_comsol_installs(). Force the scan to return [] to simulate
        # a host with no COMSOL install.
        from sim.drivers.comsol import driver as comsol_driver_mod
        monkeypatch.setattr(comsol_driver_mod, "_scan_comsol_installs", lambda: [])
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
    def test_run_file_invokes_python_subprocess(self, monkeypatch, tmp_path):
        """driver.run_file shells out to the running Python with the script."""
        import sys as _sys
        from types import SimpleNamespace

        from sim.drivers.comsol import driver as comsol_driver_mod

        script = tmp_path / "smoke.py"
        script.write_text("import mph\nclient = mph.start()\n")

        captured = {}

        def fake_run(command, capture_output, text):
            captured["command"] = command
            return SimpleNamespace(returncode=0, stdout="{}", stderr="")

        monkeypatch.setattr("sim.runner.subprocess.run", fake_run)

        driver = ComsolDriver()
        result = driver.run_file(script)

        assert captured["command"][0] == _sys.executable
        assert captured["command"][1] == str(script)
        assert result.solver == "comsol"
        assert result.exit_code == 0

    def test_run_file_routes_through_execute_script(self, monkeypatch, tmp_path):
        """The /run server path calls execute_script(driver=...), which must
        delegate to driver.run_file — this is the integration path that
        previously blew up with AttributeError."""
        from types import SimpleNamespace

        from sim import runner

        script = tmp_path / "smoke.py"
        script.write_text("import mph\n")

        def fake_run(command, capture_output, text):
            return SimpleNamespace(returncode=0, stdout="{}", stderr="")

        monkeypatch.setattr("sim.runner.subprocess.run", fake_run)

        driver = ComsolDriver()
        result = runner.execute_script(script, solver="comsol", driver=driver)
        assert result.exit_code == 0
        assert result.solver == "comsol"


def _make_import_blocker(blocked: str):
    """Return an __import__ replacement that blocks a specific module."""
    import builtins

    real_import = builtins.__import__

    def blocker(name, *args, **kwargs):
        if name == blocked or name.startswith(blocked + "."):
            raise ImportError(f"Mocked: {name} not installed")
        return real_import(name, *args, **kwargs)

    return blocker
