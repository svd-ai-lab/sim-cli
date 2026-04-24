"""Tests for sim.config — two-tier TOML config loader."""
import json
import textwrap

from click.testing import CliRunner

from sim import config as _cfg
from sim.cli import main


class TestConfigLoader:
    def test_absent_both_files(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SIM_HOME", str(tmp_path / "home-sim"))
        monkeypatch.setenv("SIM_DIR", str(tmp_path / "proj-sim"))
        _cfg.clear_cache()
        assert _cfg.load_config() == {}
        assert _cfg.resolve_server_port() == _cfg.DEFAULT_SERVER_PORT

    def test_global_only(self, tmp_path, monkeypatch):
        home = tmp_path / "home-sim"
        home.mkdir()
        (home / "config.toml").write_text(textwrap.dedent("""
            [server]
            port = 8888
            [solvers.fluent]
            path = "C:/ansys/v252"
        """))
        monkeypatch.setenv("SIM_HOME", str(home))
        monkeypatch.setenv("SIM_DIR", str(tmp_path / "proj-sim"))
        _cfg.clear_cache()
        assert _cfg.resolve_server_port() == 8888
        assert _cfg.resolve_solver_path("fluent") == "C:/ansys/v252"

    def test_project_overrides_global(self, tmp_path, monkeypatch):
        home = tmp_path / "home-sim"
        home.mkdir()
        (home / "config.toml").write_text("[server]\nport = 8888\n")
        proj = tmp_path / "proj-sim"
        proj.mkdir()
        (proj / "config.toml").write_text("[server]\nport = 9999\n")
        monkeypatch.setenv("SIM_HOME", str(home))
        monkeypatch.setenv("SIM_DIR", str(proj))
        _cfg.clear_cache()
        assert _cfg.resolve_server_port() == 9999

    def test_env_overrides_config(self, tmp_path, monkeypatch):
        proj = tmp_path / "proj-sim"
        proj.mkdir()
        (proj / "config.toml").write_text("[server]\nport = 9999\n")
        monkeypatch.setenv("SIM_HOME", str(tmp_path / "home-sim"))
        monkeypatch.setenv("SIM_DIR", str(proj))
        monkeypatch.setenv("SIM_PORT", "12345")
        _cfg.clear_cache()
        assert _cfg.resolve_server_port() == 12345

    def test_malformed_toml_falls_back(self, tmp_path, monkeypatch):
        home = tmp_path / "home-sim"
        home.mkdir()
        (home / "config.toml").write_text("this is {{ broken } toml")
        monkeypatch.setenv("SIM_HOME", str(home))
        monkeypatch.setenv("SIM_DIR", str(tmp_path / "proj-sim"))
        _cfg.clear_cache()
        # Should not raise; should fall back to defaults
        assert _cfg.resolve_server_port() == _cfg.DEFAULT_SERVER_PORT

    def test_init_project_stub(self, tmp_path, monkeypatch):
        proj = tmp_path / "proj-sim"
        monkeypatch.setenv("SIM_DIR", str(proj))
        monkeypatch.setenv("SIM_HOME", str(tmp_path / "home-sim"))
        path = _cfg.init_config_file("project")
        assert path == proj / "config.toml"
        assert path.is_file()
        assert "[solvers.fluent]" in path.read_text(encoding="utf-8")

    def test_init_does_not_overwrite(self, tmp_path, monkeypatch):
        proj = tmp_path / "proj-sim"
        proj.mkdir()
        existing = proj / "config.toml"
        existing.write_text("# user-edited\n[server]\nport = 4321\n")
        monkeypatch.setenv("SIM_DIR", str(proj))
        monkeypatch.setenv("SIM_HOME", str(tmp_path / "home-sim"))
        _cfg.init_config_file("project")
        assert "# user-edited" in existing.read_text(encoding="utf-8")


class TestConfigCLI:
    def test_config_path(self, tmp_path):
        runner = CliRunner()
        env = {
            "SIM_HOME": str(tmp_path / "home-sim"),
            "SIM_DIR": str(tmp_path / "proj-sim"),
        }
        result = runner.invoke(main, ["--json", "config", "path"], env=env)
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["global"].endswith("config.toml")
        assert data["project"].endswith("config.toml")
        assert data["global_exists"] is False
        assert data["history"].endswith("history.jsonl")

    def test_config_show_default(self, tmp_path):
        runner = CliRunner()
        env = {
            "SIM_HOME": str(tmp_path / "home-sim"),
            "SIM_DIR": str(tmp_path / "proj-sim"),
        }
        result = runner.invoke(main, ["--json", "config", "show"], env=env)
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["server_port"] == _cfg.DEFAULT_SERVER_PORT

    def test_config_init(self, tmp_path):
        runner = CliRunner()
        env = {
            "SIM_HOME": str(tmp_path / "home-sim"),
            "SIM_DIR": str(tmp_path / "proj-sim"),
        }
        result = runner.invoke(main, ["--json", "config", "init"], env=env)
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["ok"] is True
        assert (tmp_path / "proj-sim" / "config.toml").is_file()
