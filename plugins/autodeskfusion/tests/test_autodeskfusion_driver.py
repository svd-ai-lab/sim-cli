from __future__ import annotations

import json
from pathlib import Path

import pytest

from sim.driver import SolverInstall
from sim_plugin_autodeskfusion import AutodeskFusionDriver, plugin_info, skills_dir
import sim_plugin_autodeskfusion.driver as driver_mod


FIXTURES = Path(__file__).parent / "fixtures"


def _capabilities(*tools: dict) -> dict:
    return {"tools": {"tools": list(tools)}, "resources": {"resources": []}, "prompts": {"prompts": []}}


def _tool(name: str, properties: dict | None = None) -> dict:
    return {
        "name": name,
        "inputSchema": {
            "type": "object",
            "properties": properties or {"script": {"type": "string"}},
        },
    }


class FakeMcpFactory:
    def __init__(self, behavior: dict[str, dict | Exception] | None = None):
        self.behavior = behavior or {}
        self.calls: list[tuple[str, str, dict | None]] = []

    def __call__(self, url: str, timeout_s: float):
        outer = self

        class Client:
            def capabilities(self):
                outer.calls.append(("capabilities", url, None))
                item = outer.behavior.get(url)
                if isinstance(item, Exception):
                    raise item
                return item or _capabilities(_tool("fusion_mcp_execute"))

            def call_tool(self, name: str, arguments: dict):
                outer.calls.append(("call_tool", url, {"name": name, "arguments": arguments}))
                return {"content": [{"type": "text", "text": "ok"}], "isError": False}

        return Client()


def test_plugin_metadata_exports():
    assert plugin_info["name"] == "autodeskfusion"
    assert skills_dir.name == "_skills"


class TestDetect:
    def test_detects_adsk_script(self):
        assert AutodeskFusionDriver().detect(FIXTURES / "good_fusion_script.py") is True

    def test_rejects_plain_python(self):
        assert AutodeskFusionDriver().detect(FIXTURES / "not_fusion.py") is False

    def test_missing_is_false(self):
        assert AutodeskFusionDriver().detect(Path("/no/such/fusion.py")) is False


class TestLint:
    def test_good_script(self):
        result = AutodeskFusionDriver().lint(FIXTURES / "good_fusion_script.py")
        assert result.ok is True

    def test_plain_python_warns_but_is_valid_python(self):
        result = AutodeskFusionDriver().lint(FIXTURES / "not_fusion.py")
        assert result.ok is True
        assert any("adsk" in d.message for d in result.diagnostics)

    def test_bad_syntax(self):
        result = AutodeskFusionDriver().lint(FIXTURES / "bad_syntax.py")
        assert result.ok is False
        assert result.diagnostics[0].line == 2

    def test_wrong_suffix(self, tmp_path):
        path = tmp_path / "model.txt"
        path.write_text("import adsk.core\n")
        assert AutodeskFusionDriver().lint(path).ok is False


class TestConnect:
    def test_not_installed_and_no_mcp(self, monkeypatch):
        factory = FakeMcpFactory({driver_mod.DEFAULT_MCP_URL: ConnectionError("closed")})
        monkeypatch.setattr(driver_mod, "_discover_process_mcp_urls", lambda: [])

        driver = AutodeskFusionDriver(mcp_client_factory=factory)
        monkeypatch.setattr(driver, "detect_installed", lambda: [])
        info = driver.connect()

        assert info.status == "not_installed"
        assert "SIM_AUTODESKFUSION_MCP_URL" in info.message

    def test_found_install_and_mcp(self, monkeypatch, tmp_path):
        factory = FakeMcpFactory()
        monkeypatch.setattr(driver_mod, "_discover_process_mcp_urls", lambda: [])
        driver = AutodeskFusionDriver(session_dir=tmp_path, mcp_client_factory=factory)
        monkeypatch.setattr(
            driver,
            "detect_installed",
            lambda: [
                SolverInstall(
                    name="autodeskfusion",
                    version="2702.1.58",
                    path="/fake",
                    source="test",
                    extra={"exe": "/fake/Fusion360.exe"},
                )
            ],
        )

        info = driver.connect()

        assert info.status == "ok"
        assert info.version == "2702.1.58"
        assert "fusion_mcp_execute" in info.message


def test_detect_installed_from_env(monkeypatch, tmp_path):
    exe = tmp_path / "Fusion360.exe"
    exe.write_text("fake exe")
    api = tmp_path / "Autodesk Fusion 360" / "API"
    api.mkdir(parents=True)
    (api.parent / "Fusion360_2702.1.58_addins_to_load.xml").write_text("<xml />")

    monkeypatch.setenv("SIM_AUTODESKFUSION_EXE", str(exe))
    monkeypatch.setattr(driver_mod, "_default_windows_exes", lambda: [])
    monkeypatch.setattr(driver_mod, "_default_macos_exes", lambda: [])

    [install] = AutodeskFusionDriver(api_dir=api).detect_installed()
    assert install.name == "autodeskfusion"
    assert install.version == "2702.1.58"
    assert install.source == "env:SIM_AUTODESKFUSION_EXE"
    assert install.extra["exe"] == str(exe)


def test_parse_output_last_json_wins():
    out = AutodeskFusionDriver().parse_output('banner\n{"old": false}\n{"ok": true}\n')
    assert out == {"ok": True}


def test_endpoint_override_from_env(monkeypatch, tmp_path):
    factory = FakeMcpFactory()
    monkeypatch.setenv("SIM_AUTODESKFUSION_MCP_URL", "http://127.0.0.1:55484/mcp")
    monkeypatch.setattr(driver_mod, "_discover_process_mcp_urls", lambda: [])

    driver = AutodeskFusionDriver(session_dir=tmp_path, mcp_client_factory=factory)
    info = driver.connect()

    assert info.status == "ok"
    assert factory.calls[0][1] == "http://127.0.0.1:55484/mcp"


def test_endpoint_override_from_driver_option(monkeypatch, tmp_path):
    factory = FakeMcpFactory()
    monkeypatch.setattr(driver_mod, "_discover_process_mcp_urls", lambda: [])

    driver = AutodeskFusionDriver(session_dir=tmp_path, mcp_client_factory=factory)
    info = driver.launch(mcp_url="55484")

    assert info["endpoint"] == "http://127.0.0.1:55484/mcp"
    assert factory.calls[0][1] == "http://127.0.0.1:55484/mcp"


def test_default_port_conflict_uses_discovery_fallback(monkeypatch, tmp_path):
    discovered = "http://127.0.0.1:55484/mcp"
    factory = FakeMcpFactory({
        driver_mod.DEFAULT_MCP_URL: RuntimeError("not an MCP server"),
        discovered: _capabilities(_tool("fusion_mcp_execute")),
    })
    monkeypatch.setattr(driver_mod, "_discover_process_mcp_urls", lambda: [discovered])

    driver = AutodeskFusionDriver(session_dir=tmp_path, mcp_client_factory=factory)
    info = driver.launch()

    assert info["endpoint"] == discovered
    assert [call[1] for call in factory.calls[:2]] == [driver_mod.DEFAULT_MCP_URL, discovered]


def test_discovery_failure_message_mentions_port_conflict(monkeypatch, tmp_path):
    factory = FakeMcpFactory({driver_mod.DEFAULT_MCP_URL: RuntimeError("wrong service")})
    monkeypatch.setattr(driver_mod, "_discover_process_mcp_urls", lambda: [])

    driver = AutodeskFusionDriver(session_dir=tmp_path, mcp_client_factory=factory)
    with pytest.raises(RuntimeError, match="default port"):
        driver.launch()


class TestRunFile:
    def test_wrong_suffix_raises(self, tmp_path):
        path = tmp_path / "x.txt"
        path.write_text("import adsk.core\n")
        with pytest.raises(RuntimeError, match=r"\.py"):
            AutodeskFusionDriver().run_file(path)

    def test_calls_execute_tool_and_returns_run_result(self, monkeypatch, tmp_path):
        factory = FakeMcpFactory()
        monkeypatch.setattr(driver_mod, "_discover_process_mcp_urls", lambda: [])
        driver = AutodeskFusionDriver(session_dir=tmp_path, mcp_client_factory=factory)

        result = driver.run_file(FIXTURES / "good_fusion_script.py")
        parsed = json.loads(result.stdout)

        assert result.exit_code == 0
        assert parsed["tool"] == "fusion_mcp_execute"
        call = [item for item in factory.calls if item[0] == "call_tool"][0]
        assert call[2]["name"] == "fusion_mcp_execute"
        script = call[2]["arguments"]["script"]
        assert "def run" in script
        assert "SIM_AUTODESKFUSION_OUT" in script

    def test_schema_based_execute_field_selection(self, monkeypatch, tmp_path):
        caps = _capabilities(_tool("run_script", {"payload": {"type": "string"}}))
        factory = FakeMcpFactory({driver_mod.DEFAULT_MCP_URL: caps})
        monkeypatch.setattr(driver_mod, "_discover_process_mcp_urls", lambda: [])
        driver = AutodeskFusionDriver(session_dir=tmp_path, mcp_client_factory=factory)

        result = driver.run("import adsk.core\nprint('hi')", label="unit")

        assert result["ok"] is True
        call = [item for item in factory.calls if item[0] == "call_tool"][0]
        assert call[2]["name"] == "run_script"
        assert list(call[2]["arguments"]) == ["payload"]

    def test_official_fusion_execute_schema_uses_feature_object(self, monkeypatch, tmp_path):
        caps = _capabilities(
            _tool(
                "fusion_mcp_execute",
                {
                    "featureType": {"type": "string", "enum": ["script", "document"]},
                    "object": {
                        "type": "object",
                        "properties": {"script": {"type": "string"}},
                    },
                },
            )
        )
        factory = FakeMcpFactory({driver_mod.DEFAULT_MCP_URL: caps})
        monkeypatch.setattr(driver_mod, "_discover_process_mcp_urls", lambda: [])
        driver = AutodeskFusionDriver(session_dir=tmp_path, mcp_client_factory=factory)

        result = driver.run("import adsk.core\nprint('hi')", label="unit")

        assert result["ok"] is True
        assert result["execute_field"] == "object.script"
        call = [item for item in factory.calls if item[0] == "call_tool"][0]
        assert call[2]["arguments"]["featureType"] == "script"
        assert "def run" in call[2]["arguments"]["object"]["script"]

    def test_execute_failure_is_structured(self, monkeypatch, tmp_path):
        factory = FakeMcpFactory({driver_mod.DEFAULT_MCP_URL: RuntimeError("closed")})
        monkeypatch.setattr(driver_mod, "_discover_process_mcp_urls", lambda: [])
        driver = AutodeskFusionDriver(session_dir=tmp_path, mcp_client_factory=factory)

        result = driver.run("import adsk.core\nprint('hi')", label="unit")

        assert result["ok"] is False
        assert result["error_code"] == "session_unavailable"
        assert "SIM_AUTODESKFUSION_MCP_URL" in result["error"]


def test_legacy_bridge_transport_removed(monkeypatch, tmp_path):
    monkeypatch.setenv("SIM_AUTODESKFUSION_TRANSPORT", "bridge")
    driver = AutodeskFusionDriver(session_dir=tmp_path, mcp_client_factory=FakeMcpFactory())

    with pytest.raises(RuntimeError, match="SimFusionBridge"):
        driver.launch()
