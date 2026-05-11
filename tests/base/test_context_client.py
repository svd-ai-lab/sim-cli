import json

from click.testing import CliRunner

from sim import config as _cfg
from sim import context_client
from sim.cli import main


def _pack():
    return {
        "schema_version": "context_pack_v1",
        "domain": "comsol",
        "mode": "context_only",
        "llm_used": False,
        "usage": {
            "returned_example_count": 1,
            "context_block_count": 1,
            "estimated_returned_tokens": 42,
        },
        "recommended_examples": [
            {
                "id": "seed_surface_mount_package_847",
                "title": "Heat Transfer in a Surface-Mount Package for a Silicon Chip",
                "summary": "Electronics cooling context.",
                "source_kind": "online_application_gallery_example",
                "source_pointer": {
                    "url": "https://www.comsol.com/model/heat-transfer-in-a-surface-mount-package-for-a-silicon-chip-847"
                },
            }
        ],
        "agent_hints": {
            "physics": ["Use Heat Transfer in Solids."]
        },
    }


def test_context_config_resolvers(tmp_path, monkeypatch):
    proj = tmp_path / "proj-sim"
    proj.mkdir()
    (proj / "config.toml").write_text(
        "[context]\napi_base_url = \"http://127.0.0.1:8088/api/v1\"\napi_key = \"sim_sk_config\"\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SIM_HOME", str(tmp_path / "home-sim"))
    monkeypatch.setenv("SIM_DIR", str(proj))
    monkeypatch.delenv("SIM_CONTEXT_API_BASE_URL", raising=False)
    monkeypatch.delenv("SIM_CONTEXT_API_KEY", raising=False)
    _cfg.clear_cache()

    assert _cfg.resolve_context_api_base_url() == "http://127.0.0.1:8088/api/v1"
    assert _cfg.resolve_context_api_key() == "sim_sk_config"

    monkeypatch.setenv("SIM_CONTEXT_API_BASE_URL", "http://localhost:9999/api/v1/")
    monkeypatch.setenv("SIM_CONTEXT_API_KEY", "sim_sk_env")
    assert _cfg.resolve_context_api_base_url() == "http://localhost:9999/api/v1"
    assert _cfg.resolve_context_api_key() == "sim_sk_env"


def test_config_show_redacts_context_api_key(tmp_path, monkeypatch):
    proj = tmp_path / "proj-sim"
    proj.mkdir()
    (proj / "config.toml").write_text("[context]\napi_key = \"sim_sk_secret\"\n", encoding="utf-8")
    monkeypatch.setenv("SIM_HOME", str(tmp_path / "home-sim"))
    monkeypatch.setenv("SIM_DIR", str(proj))
    monkeypatch.delenv("SIM_CONTEXT_API_KEY", raising=False)
    _cfg.clear_cache()

    result = CliRunner().invoke(main, ["--json", "config", "show"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["context_api_key_configured"] is True
    assert "sim_sk_secret" not in result.output
    assert data["merged"]["context"]["api_key"] == "***configured***"


def test_context_get_json(monkeypatch, tmp_path):
    def fake_get_context(**kwargs):
        assert kwargs["domain"] == "comsol"
        assert kwargs["query"] == "chip cooling"
        assert kwargs["source_preference"] == "any"
        return _pack()

    monkeypatch.setenv("SIM_HOME", str(tmp_path / "home-sim"))
    monkeypatch.setenv("SIM_DIR", str(tmp_path / "proj-sim"))
    monkeypatch.setattr(context_client, "get_context", fake_get_context)

    result = CliRunner().invoke(main, ["--json", "context", "get", "--domain", "comsol", "chip cooling"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["schema_version"] == "context_pack_v1"
    assert data["recommended_examples"][0]["id"] == "seed_surface_mount_package_847"


def test_context_get_missing_key(monkeypatch, tmp_path):
    monkeypatch.setenv("SIM_HOME", str(tmp_path / "home-sim"))
    monkeypatch.setenv("SIM_DIR", str(tmp_path / "proj-sim"))
    monkeypatch.delenv("SIM_CONTEXT_API_KEY", raising=False)
    _cfg.clear_cache()

    result = CliRunner().invoke(main, ["--json", "context", "get", "chip cooling"])

    assert result.exit_code == 2
    data = json.loads(result.output)
    assert data["error_code"] == "CONTEXT_API_KEY_MISSING"
    assert "fallback" in data


def test_context_get_api_error(monkeypatch, tmp_path):
    def fake_get_context(**kwargs):
        raise context_client.ContextApiError(429, "CONTEXT_API_RATE_LIMITED", "Rate limit exceeded.")

    monkeypatch.setenv("SIM_HOME", str(tmp_path / "home-sim"))
    monkeypatch.setenv("SIM_DIR", str(tmp_path / "proj-sim"))
    monkeypatch.setattr(context_client, "get_context", fake_get_context)

    result = CliRunner().invoke(main, ["--json", "context", "get", "chip cooling"])

    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["error_code"] == "CONTEXT_API_RATE_LIMITED"
    assert data["status_code"] == 429
