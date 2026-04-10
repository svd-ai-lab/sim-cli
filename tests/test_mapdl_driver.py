"""Tests for the MAPDL driver."""
from pathlib import Path

from sim.driver import SolverInstall
from sim.drivers.mapdl import MapdlDriver


class TestMapdlDetect:
    def test_detects_inp_script(self, tmp_path):
        script = tmp_path / "beam.inp"
        script.write_text("/prep7\nfinish\n")
        driver = MapdlDriver()
        assert driver.detect(script) is True

    def test_detects_mac_script(self, tmp_path):
        script = tmp_path / "beam.mac"
        script.write_text("/prep7\nfinish\n")
        driver = MapdlDriver()
        assert driver.detect(script) is True

    def test_rejects_python_script(self, tmp_path):
        script = tmp_path / "beam.py"
        script.write_text("print('nope')\n")
        driver = MapdlDriver()
        assert driver.detect(script) is False


class TestMapdlLint:
    def test_lint_rejects_empty_input(self, tmp_path):
        script = tmp_path / "empty.inp"
        script.write_text("")
        driver = MapdlDriver()
        result = driver.lint(script)
        assert result.ok is False
        assert "empty" in result.diagnostics[0].message.lower()

    def test_lint_accepts_nonempty_input(self, tmp_path):
        script = tmp_path / "solve.inp"
        script.write_text("/prep7\nfinish\n")
        driver = MapdlDriver()
        result = driver.lint(script)
        assert result.ok is True


class TestMapdlParseOutput:
    def test_parses_last_json_line(self):
        driver = MapdlDriver()
        payload = driver.parse_output("note\n{\"status\":\"ok\"}\n{\"value\":42}\n")
        assert payload == {"value": 42}


class TestMapdlConnect:
    def test_reports_not_installed_when_missing(self, monkeypatch):
        monkeypatch.setattr("sim.drivers.mapdl.driver._scan_mapdl_installs", lambda: [])
        driver = MapdlDriver()
        info = driver.connect()
        assert info.status == "not_installed"


class TestMapdlDetectInstalled:
    def test_deduplicates_same_install_root(self, monkeypatch):
        monkeypatch.setattr(
            "sim.drivers.mapdl.driver._env_candidates",
            lambda: [
                (Path(r"D:\ansys\ansys\ANSYS Inc\v242\ansys\bin\winx64\ANSYS242.exe"), "env:AWP_ROOT242", "242"),
                (Path(r"D:\ansys\ansys\ANSYS Inc\v242\ansys\bin\winx64\MAPDL242.exe"), "env:AWP_ROOT242", "242"),
            ],
        )
        monkeypatch.setattr("sim.drivers.mapdl.driver._path_candidates", lambda: [])
        monkeypatch.setattr("sim.drivers.mapdl.driver._default_windows_candidates", lambda: [])
        monkeypatch.setattr("pathlib.Path.is_file", lambda self: True)

        installs = MapdlDriver().detect_installed()
        assert len(installs) == 1
        assert installs[0].version == "24.2"


class TestMapdlRunFile:
    def test_uses_batch_mode_and_reads_out_file(self, monkeypatch, tmp_path):
        script = tmp_path / "demo.inp"
        script.write_text("/prep7\nfinish\n")

        monkeypatch.setattr(
            "sim.drivers.mapdl.driver._scan_mapdl_installs",
            lambda: [
                SolverInstall(
                    name="mapdl",
                    version="24.2",
                    path=r"D:\ansys\ansys\ANSYS Inc\v242",
                    source="test",
                    extra={"exe_path": r"D:\ansys\ansys\ANSYS Inc\v242\ansys\bin\winx64\ANSYS242.exe"},
                )
            ],
        )

        captured: dict = {}

        def fake_run(command, capture_output, text, cwd):
            captured["command"] = command
            captured["cwd"] = cwd
            (Path(cwd) / "demo.out").write_text("MAPDL START\n{\"status\":\"ok\"}\n", encoding="utf-8")

            class _Proc:
                returncode = 0
                stdout = ""
                stderr = ""

            return _Proc()

        monkeypatch.setattr("sim.drivers.mapdl.driver.subprocess.run", fake_run)

        driver = MapdlDriver()
        result = driver.run_file(script)

        assert result.exit_code == 0
        assert captured["command"][0].endswith("ANSYS242.exe")
        assert captured["command"][1:3] == ["-np", "1"]
        assert "-b" in captured["command"]
        assert captured["command"][-4:] == ["-i", "demo.inp", "-o", "demo.out"]
        assert captured["cwd"] == str(tmp_path)
        assert "{\"status\":\"ok\"}" in result.stdout
