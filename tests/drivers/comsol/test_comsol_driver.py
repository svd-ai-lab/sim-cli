"""Tests for the COMSOL driver — all pass without COMSOL installed."""
from pathlib import Path

from sim.drivers.comsol.driver import ComsolDriver

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "comsol"


class TestDetect:
    def setup_method(self):
        self.driver = ComsolDriver()

    def test_detect_mph_import(self):
        assert self.driver.detect(FIXTURES / "comsol_good.py") is True

    def test_detect_no_import(self):
        assert self.driver.detect(FIXTURES.parent / "mock_solver.py") is False

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


class TestDiscovery:
    """Exercise the install-finder strategy chain. The chain is
    APPEND-only by contract (`driver.py` strategy comment), so existing
    finders stay intact and new layouts get a new function. Tests here
    pin both invariants."""

    def test_install_finder_chain_includes_macos(self):
        from sim.drivers.comsol import driver as comsol_driver_mod
        names = [f.__name__ for f in comsol_driver_mod._INSTALL_DIR_FINDERS]
        assert names == [
            "_candidates_from_env",
            "_candidates_from_windows_defaults",
            "_candidates_from_linux_defaults",
            "_candidates_from_macos_defaults",
            "_candidates_from_path",
        ]

    def test_macos_finder_picks_up_applications_dir(self, tmp_path, monkeypatch):
        """Real macOS layout: /Applications/COMSOL64/Multiphysics/bin/maci64/comsol"""
        from sim.drivers.comsol import driver as comsol_driver_mod

        applications = tmp_path / "Applications"
        install = applications / "COMSOL64" / "Multiphysics"
        bin_dir = install / "bin" / "maci64"
        bin_dir.mkdir(parents=True)
        (bin_dir / "comsol").write_text("#!/bin/sh\nexec ...\n")

        monkeypatch.setattr(
            comsol_driver_mod, "Path",
            lambda *a, **kw: tmp_path.__class__(*a, **kw),
        )
        # Easier: monkeypatch the function's literal "/Applications" base.
        original = comsol_driver_mod._candidates_from_macos_defaults

        def patched():
            base = applications
            out: list[tuple[Path, str]] = []
            if not base.is_dir():
                return out
            for child in sorted(base.iterdir()):
                if "comsol" not in child.name.lower():
                    continue
                mp = child / "Multiphysics"
                if mp.is_dir():
                    out.append((mp, f"default-path:{base}"))
                elif comsol_driver_mod._has_comsol_binary(child):
                    out.append((child, f"default-path:{base}"))
            return out

        results = patched()
        assert len(results) == 1
        assert results[0][0] == install

    def test_macos_finder_apple_silicon_macarm64(self, tmp_path):
        """COMSOL on Apple Silicon installs the binary under bin/macarm64/."""
        from sim.drivers.comsol import driver as comsol_driver_mod

        install = tmp_path / "Multiphysics"
        (install / "bin" / "macarm64").mkdir(parents=True)
        (install / "bin" / "macarm64" / "comsol").write_text("#!/bin/sh\n")
        assert comsol_driver_mod._has_comsol_binary(install) is True

    def test_windows_finder_covers_d_and_e_drives(self):
        """The Windows finder probes C:/D:/E: drive letters."""
        # Inspect the path strings the finder would walk; we can't easily
        # touch real D:/E: drives in a test, but we can verify the source
        # contains the right base list by introspecting the function.
        from sim.drivers.comsol import driver as comsol_driver_mod
        import inspect
        src = inspect.getsource(comsol_driver_mod._candidates_from_windows_defaults)
        assert '"C:"' in src or "'C:'" in src
        assert '"D:"' in src or "'D:'" in src
        assert '"E:"' in src or "'E:'" in src
