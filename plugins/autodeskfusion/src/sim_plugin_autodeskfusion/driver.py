"""Autodesk Fusion driver for sim.

Fusion exposes its Python API inside the desktop process. This driver keeps the
host-side harness intentionally thin: it discovers Autodesk Fusion's official
local MCP endpoint, asks the server which tools it exposes, and calls the
best-matching execute tool without reimplementing Fusion automation.
"""
from __future__ import annotations

import ast
import asyncio
import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import io
import json
import os
import re
import subprocess
import textwrap
import threading
import time
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from sim.driver import ConnectionInfo, Diagnostic, LintResult, RunResult, SolverInstall


NAME = "autodeskfusion"
DEFAULT_MCP_URL = "http://127.0.0.1:27182/mcp"
_SCRIPT_MARKERS = ("import adsk", "from adsk", "adsk.core", "adsk.fusion", "adsk.sim")
_VERSION_RE = re.compile(r"Fusion360_([^_]+)_(?:addins_to_load|cached_addins)\.xml$", re.IGNORECASE)
_DEFAULT_TIMEOUT_S = 30.0
_EXECUTE_TOOL_HINTS = (
    "fusion_mcp_execute",
    "execute",
    "execute_code",
    "run_python",
    "python_execute",
)
_EXECUTE_FIELD_HINTS = ("script", "code", "python", "source", "program", "input")


@dataclass
class _EndpointProbe:
    ok: bool
    url: str | None
    capabilities: dict[str, Any]
    failures: list[dict[str, str]]


def _default_api_dir() -> Path:
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "Autodesk" / "Autodesk Fusion 360" / "API"
    return Path.home() / "Library" / "Application Support" / "Autodesk" / "Autodesk Fusion 360" / "API"


def _default_session_dir() -> Path:
    return Path(os.environ.get("SIM_AUTODESKFUSION_SESSION_DIR", Path.home() / ".sim" / NAME))


def _default_windows_exes() -> list[Path]:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return []
    root = Path(local) / "Autodesk" / "webdeploy" / "production"
    if not root.is_dir():
        return []
    return sorted(root.glob("*/Fusion360.exe"), reverse=True)


def _default_macos_exes() -> list[Path]:
    return [
        Path("/Applications/Autodesk Fusion.app/Contents/MacOS/Autodesk Fusion"),
        Path.home() / "Applications" / "Autodesk Fusion.app" / "Contents" / "MacOS" / "Autodesk Fusion",
    ]


def _version_from_addin_cache(api_dir: Path | None = None) -> str | None:
    if api_dir is None:
        api_dir = _default_api_dir()
    config_dir = api_dir.parent
    try:
        for path in sorted(config_dir.glob("Fusion360_*_addins_to_load.xml"), reverse=True):
            match = _VERSION_RE.match(path.name)
            if match:
                return match.group(1)
        for path in sorted(config_dir.glob("Fusion360_*_cached_addins.xml"), reverse=True):
            match = _VERSION_RE.match(path.name)
            if match:
                return match.group(1)
    except OSError:
        return None
    return None


def _candidate_exes() -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    for var in ("SIM_AUTODESKFUSION_EXE", "AUTODESK_FUSION_EXE"):
        value = os.environ.get(var)
        if value:
            out.append((Path(value), f"env:{var}"))

    if os.name == "nt":
        out.extend((path, "default-path:webdeploy") for path in _default_windows_exes())
    else:
        out.extend((path, "default-path:/Applications") for path in _default_macos_exes())
    return out


def _install_from_exe(exe: Path, source: str, api_dir: Path) -> SolverInstall | None:
    try:
        if not exe.is_file():
            return None
    except OSError:
        return None
    version = _version_from_addin_cache(api_dir) or "unknown"
    return SolverInstall(
        name=NAME,
        version=version,
        path=str(exe.parent),
        source=source,
        extra={
            "exe": str(exe),
            "api_dir": str(api_dir),
            "default_mcp_url": DEFAULT_MCP_URL,
        },
    )


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True)
    if hasattr(value, "dict"):
        return value.dict()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _run_async(factory: Callable[[], Any]) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    box: dict[str, Any] = {}

    def worker() -> None:
        try:
            box["value"] = asyncio.run(factory())
        except BaseException as exc:  # noqa: BLE001 - re-raised in caller thread
            box["error"] = exc

    thread = threading.Thread(target=worker, name="autodeskfusion-mcp-client", daemon=True)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]
    return box.get("value")


class AutodeskFusionMcpClient:
    """Small synchronous wrapper around the official MCP Python SDK."""

    def __init__(self, url: str, timeout_s: float) -> None:
        self.url = url
        self.timeout_s = timeout_s

    def capabilities(self) -> dict[str, Any]:
        return _run_async(lambda: self._capabilities())

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return _run_async(lambda: self._call_tool(name, arguments))

    async def _capabilities(self) -> dict[str, Any]:
        import httpx
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        timeout = httpx.Timeout(self.timeout_s)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with streamable_http_client(self.url, http_client=client) as (read, write, _session_id):
                async with ClientSession(read, write) as session:
                    initialized = await session.initialize()
                    tools = await session.list_tools()
                    out = {
                        "initialize": _jsonable(initialized),
                        "tools": _jsonable(tools),
                    }
                    try:
                        out["resources"] = _jsonable(await session.list_resources())
                    except Exception as exc:  # noqa: BLE001 - optional capability
                        out["resources"] = {"error": f"{type(exc).__name__}: {exc}"}
                    try:
                        out["prompts"] = _jsonable(await session.list_prompts())
                    except Exception as exc:  # noqa: BLE001 - optional capability
                        out["prompts"] = {"error": f"{type(exc).__name__}: {exc}"}
                    return out

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        import httpx
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        timeout = httpx.Timeout(self.timeout_s)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with streamable_http_client(self.url, http_client=client) as (read, write, _session_id):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        name,
                        arguments,
                        read_timeout_seconds=timedelta(seconds=self.timeout_s),
                    )
                    return _jsonable(result)


def _normalize_mcp_url(value: str) -> str:
    value = value.strip()
    if not value:
        return value
    if value.isdigit():
        return f"http://127.0.0.1:{value}/mcp"
    if "://" not in value:
        value = f"http://{value}"
    if value.endswith("/"):
        value = value[:-1]
    if value.rsplit("/", 1)[-1] != "mcp":
        value = f"{value}/mcp"
    return value


def _split_url_list(value: str | None) -> list[str]:
    if not value:
        return []
    pieces = re.split(r"[;,]", value)
    return [_normalize_mcp_url(piece) for piece in pieces if piece.strip()]


def _parse_host_port(local_address: str) -> tuple[str, int] | None:
    address = local_address.strip()
    if address.startswith("[") and "]:" in address:
        host, port = address[1:].rsplit("]:", 1)
    elif ":" in address:
        host, port = address.rsplit(":", 1)
    else:
        return None
    try:
        return host, int(port)
    except ValueError:
        return None


def _discover_windows_fusion_mcp_urls() -> list[str]:
    pids: set[str] = set()
    try:
        tasklist = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Fusion360.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        for row in csv.reader(io.StringIO(tasklist.stdout)):
            if len(row) >= 2 and row[0].lower().endswith("fusion360.exe"):
                pids.add(row[1])
    except (OSError, subprocess.SubprocessError):
        return []
    if not pids:
        return []

    urls: list[str] = []
    try:
        netstat = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    for line in netstat.stdout.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP" or parts[-2].upper() != "LISTENING":
            continue
        pid = parts[-1]
        if pid not in pids:
            continue
        parsed = _parse_host_port(parts[1])
        if parsed is None:
            continue
        host, port = parsed
        if host in ("127.0.0.1", "localhost", "::1"):
            urls.append(f"http://127.0.0.1:{port}/mcp")
    return urls


def _discover_macos_fusion_mcp_urls() -> list[str]:
    try:
        lsof = subprocess.run(
            ["lsof", "-nP", "-a", "-c", "Fusion", "-iTCP", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    urls: list[str] = []
    for line in lsof.stdout.splitlines()[1:]:
        fields = line.split()
        if not fields:
            continue
        endpoint = fields[-2] if fields[-1] == "(LISTEN)" and len(fields) >= 2 else fields[-1]
        parsed = _parse_host_port(endpoint)
        if parsed is None:
            continue
        host, port = parsed
        if host in ("127.0.0.1", "localhost", "::1"):
            urls.append(f"http://127.0.0.1:{port}/mcp")
    return urls


def _discover_process_mcp_urls() -> list[str]:
    if os.name == "nt":
        return _discover_windows_fusion_mcp_urls()
    if os.name == "posix":
        return _discover_macos_fusion_mcp_urls()
    return []


def _tools_from_capabilities(capabilities: dict[str, Any]) -> list[dict[str, Any]]:
    tools = capabilities.get("tools", {})
    if isinstance(tools, dict):
        raw = tools.get("tools", [])
    else:
        raw = tools
    return [tool for tool in raw if isinstance(tool, dict)]


def _tool_names(capabilities: dict[str, Any]) -> list[str]:
    return [tool.get("name", "") for tool in _tools_from_capabilities(capabilities) if tool.get("name")]


def _tool_schema(tool: dict[str, Any]) -> dict[str, Any]:
    schema = tool.get("inputSchema") or tool.get("input_schema") or {}
    return schema if isinstance(schema, dict) else {}


def _find_tool(tools: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for tool in tools:
        if tool.get("name") == name:
            return tool
    return None


def _select_execute_tool(tools: list[dict[str, Any]], preferred: str | None = None) -> tuple[str, dict[str, Any]]:
    names = {tool.get("name"): tool for tool in tools if tool.get("name")}
    if preferred:
        tool = names.get(preferred)
        if tool is not None:
            return preferred, tool
        raise RuntimeError(f"Configured execute tool {preferred!r} was not found. Discovered: {', '.join(names)}")
    for hint in _EXECUTE_TOOL_HINTS:
        tool = names.get(hint)
        if tool is not None:
            return hint, tool
    for name, tool in names.items():
        lowered = name.lower()
        if "execute" in lowered and ("fusion" in lowered or "python" in lowered or "script" in lowered):
            return name, tool
    for name, tool in names.items():
        lowered = name.lower()
        if "run" in lowered and ("fusion" in lowered or "python" in lowered or "script" in lowered):
            return name, tool
    raise RuntimeError(f"No execute-capable Fusion MCP tool found. Discovered: {', '.join(names) or '(none)'}")


def _select_execute_field(tool: dict[str, Any], preferred: str | None = None) -> str:
    schema = _tool_schema(tool)
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return preferred or "script"
    if preferred:
        if preferred in properties:
            return preferred
        raise RuntimeError(f"Configured execute field {preferred!r} was not found in tool schema")
    for hint in _EXECUTE_FIELD_HINTS:
        if hint in properties:
            return hint
    string_fields = [
        name
        for name, prop in properties.items()
        if isinstance(prop, dict) and prop.get("type") in (None, "string")
    ]
    if len(string_fields) == 1:
        return string_fields[0]
    return "script"


def _build_execute_arguments(tool: dict[str, Any], script: str, preferred: str | None = None) -> tuple[dict[str, Any], str]:
    schema = _tool_schema(tool)
    properties = schema.get("properties") if isinstance(schema, dict) else {}
    if not preferred and isinstance(properties, dict):
        feature_type = properties.get("featureType")
        object_prop = properties.get("object")
        object_properties = object_prop.get("properties") if isinstance(object_prop, dict) else None
        feature_enum = feature_type.get("enum") if isinstance(feature_type, dict) else None
        if (
            isinstance(feature_enum, list)
            and "script" in feature_enum
            and isinstance(object_properties, dict)
            and "script" in object_properties
        ):
            return {"featureType": "script", "object": {"script": script}}, "object.script"
    field = _select_execute_field(tool, preferred)
    return {field: script}, field


def _tool_call_is_error(result: dict[str, Any]) -> bool:
    return bool(result.get("isError") or result.get("is_error"))


def _read_json_if_present(path: Path) -> dict[str, Any] | None:
    try:
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _has_run_entrypoint(source: str) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    return any(isinstance(node, ast.FunctionDef) and node.name == "run" for node in tree.body)


class AutodeskFusionDriver:
    """Autodesk Fusion driver backed by the official local MCP server."""

    def __init__(
        self,
        *,
        api_dir: str | os.PathLike[str] | None = None,
        session_dir: str | os.PathLike[str] | None = None,
        mcp_url: str | None = None,
        timeout_s: float | None = None,
        mcp_client_factory: Callable[[str, float], Any] | None = None,
    ) -> None:
        self.api_dir = Path(api_dir) if api_dir is not None else _default_api_dir()
        self.session_dir = Path(session_dir) if session_dir is not None else _default_session_dir()
        self.timeout_s = timeout_s if timeout_s is not None else float(
            os.environ.get("SIM_AUTODESKFUSION_TIMEOUT_S", _DEFAULT_TIMEOUT_S)
        )
        self._configured_mcp_url = _normalize_mcp_url(mcp_url) if mcp_url else None
        self._mcp_client_factory = mcp_client_factory or AutodeskFusionMcpClient
        self._session_id: str | None = None
        self._mcp_url: str | None = None
        self._capabilities: dict[str, Any] = {}
        self._execute_tool: str | None = None
        self._execute_field: str | None = None

    @property
    def name(self) -> str:
        return NAME

    @property
    def supports_session(self) -> bool:
        return True

    def detect(self, script: Path) -> bool:
        try:
            if script.suffix.lower() != ".py" or not script.is_file():
                return False
            text = script.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        lowered = text.lower()
        return any(marker in lowered for marker in _SCRIPT_MARKERS)

    def lint(self, script: Path) -> LintResult:
        if script.suffix.lower() != ".py":
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(level="error", message="Autodesk Fusion scripts must be Python .py files")],
            )
        try:
            text = script.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return LintResult(ok=False, diagnostics=[Diagnostic(level="error", message=f"Cannot read: {exc}")])
        try:
            ast.parse(text, filename=str(script))
        except SyntaxError as exc:
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(level="error", message=exc.msg, line=exc.lineno)],
            )
        diagnostics: list[Diagnostic] = []
        if not any(marker in text.lower() for marker in _SCRIPT_MARKERS):
            diagnostics.append(Diagnostic(level="warning", message="No Fusion `adsk` API import or usage detected"))
        return LintResult(ok=True, diagnostics=diagnostics)

    def connect(self) -> ConnectionInfo:
        installs = self.detect_installed()
        probe = self._probe_endpoint()
        version = installs[0].version if installs else None
        if probe.ok:
            tools = ", ".join(_tool_names(probe.capabilities)[:6]) or "no tools reported"
            return ConnectionInfo(
                solver=self.name,
                version=version or "unknown",
                status="ok",
                message=f"Autodesk Fusion MCP reachable at {probe.url}; tools: {tools}",
                solver_version=version,
            )
        if installs:
            return ConnectionInfo(
                solver=self.name,
                version=version,
                status="error",
                message=self._probe_failure_message(probe),
                solver_version=version,
            )
        return ConnectionInfo(
            solver=self.name,
            version=None,
            status="not_installed",
            message=(
                "Autodesk Fusion install and MCP endpoint were not found. "
                "Set SIM_AUTODESKFUSION_EXE for install detection or "
                "SIM_AUTODESKFUSION_MCP_URL for a running Fusion MCP endpoint. "
                f"{self._probe_failure_message(probe)}"
            ),
        )

    def detect_installed(self) -> list[SolverInstall]:
        found: dict[str, SolverInstall] = {}
        for exe, source in _candidate_exes():
            install = _install_from_exe(exe, source=source, api_dir=self.api_dir)
            if install is None:
                continue
            key = str(Path(install.extra["exe"]).resolve())
            found.setdefault(key, install)
        return list(found.values())

    def parse_output(self, stdout: str) -> dict:
        try:
            parsed = json.loads(stdout)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            pass
        for line in reversed(stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    continue
                return parsed if isinstance(parsed, dict) else {}
        return {}

    def run_file(self, script: Path) -> RunResult:
        if script.suffix.lower() != ".py":
            raise RuntimeError(f"{self.name} driver only accepts .py scripts (got {script.suffix})")
        lint = self.lint(script)
        if not lint.ok:
            messages = "; ".join(d.message for d in lint.diagnostics)
            raise RuntimeError(f"Autodesk Fusion script failed lint: {messages}")

        started = time.time()
        source = script.read_text(encoding="utf-8")
        result = self._execute_source(source, label=script.stem)
        stdout = json.dumps(result, separators=(",", ":"), default=str)
        ok = bool(result.get("ok", False))
        artifacts = []
        result_path = result.get("result_path")
        if result_path:
            artifacts.append({"path": result_path, "kind": "json", "role": "script-result"})
        return RunResult(
            exit_code=0 if ok else 1,
            stdout=stdout,
            stderr=result.get("stderr", ""),
            duration_s=round(time.time() - started, 3),
            script=str(Path(script).resolve()),
            solver=self.name,
            timestamp=datetime.now(timezone.utc).isoformat(),
            errors=[] if ok else [result.get("error", "Autodesk Fusion MCP execution failed")],
            artifacts=artifacts,
        )

    def launch(self, **kwargs) -> dict:
        self._reject_legacy_transport(kwargs.get("transport"))
        override_url = kwargs.get("mcp_url") or kwargs.get("endpoint")
        self._execute_tool = kwargs.get("execute_tool") or os.environ.get("SIM_AUTODESKFUSION_EXECUTE_TOOL")
        self._execute_field = kwargs.get("execute_field") or os.environ.get("SIM_AUTODESKFUSION_EXECUTE_FIELD")
        probe = self._probe_endpoint(override_url=override_url)
        if not probe.ok:
            raise RuntimeError(self._probe_failure_message(probe))
        self._session_id = self._session_id or uuid4().hex
        self._mcp_url = probe.url
        self._capabilities = probe.capabilities
        return {
            "ok": True,
            "session_id": self._session_id,
            "endpoint": probe.url,
            "transport": "mcp",
            "tools": _tool_names(probe.capabilities),
            "launch_options": {
                "endpoint": probe.url,
                "transport": "mcp",
                "tool_count": len(_tool_names(probe.capabilities)),
            },
        }

    def run(self, code: str, label: str = "") -> dict:
        started = time.time()
        result = self._execute_source(code, label=label or "snippet")
        result.setdefault("duration_s", round(time.time() - started, 3))
        result.setdefault("label", label)
        return result

    def query(self, name: str) -> dict:
        if name in ("session.versions", "mcp.endpoint", "mcp.capabilities", "mcp.tools", "mcp.resources", "mcp.prompts"):
            probe = self._probe_endpoint(override_url=self._mcp_url)
            if not probe.ok:
                return {"ok": False, "error": self._probe_failure_message(probe), "failures": probe.failures}
            data: dict[str, Any] = {
                "ok": True,
                "endpoint": probe.url,
                "transport": "mcp",
                "tools": _tool_names(probe.capabilities),
            }
            if name == "session.versions":
                data["solver"] = self.name
                data["version"] = (self.detect_installed()[0].version if self.detect_installed() else "unknown")
            elif name == "mcp.capabilities":
                data["capabilities"] = probe.capabilities
            elif name == "mcp.tools":
                data["tools_detail"] = _tools_from_capabilities(probe.capabilities)
            elif name == "mcp.resources":
                data["resources"] = probe.capabilities.get("resources")
            elif name == "mcp.prompts":
                data["prompts"] = probe.capabilities.get("prompts")
            return data
        return {"ok": False, "error": f"unknown inspect target: {name}"}

    def disconnect(self) -> dict:
        self._session_id = None
        self._mcp_url = None
        self._capabilities = {}
        return {"ok": True, "disconnected": True}

    def _candidate_mcp_urls(self, override_url: str | None = None) -> list[str]:
        urls: list[str] = []
        if override_url:
            urls.append(_normalize_mcp_url(str(override_url)))
        if self._configured_mcp_url:
            urls.append(self._configured_mcp_url)
        urls.extend(_split_url_list(os.environ.get("SIM_AUTODESKFUSION_MCP_URL")))
        urls.extend(_split_url_list(os.environ.get("SIM_AUTODESKFUSION_MCP_URLS")))
        urls.append(DEFAULT_MCP_URL)
        urls.extend(_discover_process_mcp_urls())

        seen: set[str] = set()
        out: list[str] = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                out.append(url)
        return out

    def _probe_endpoint(self, override_url: str | None = None) -> _EndpointProbe:
        failures: list[dict[str, str]] = []
        for url in self._candidate_mcp_urls(override_url):
            try:
                capabilities = self._mcp_client_factory(url, self.timeout_s).capabilities()
                if not isinstance(capabilities, dict):
                    raise RuntimeError(f"MCP capabilities were {type(capabilities).__name__}, expected dict")
                return _EndpointProbe(ok=True, url=url, capabilities=capabilities, failures=failures)
            except Exception as exc:  # noqa: BLE001 - every candidate failure is diagnostic data
                failures.append({"url": url, "error": f"{type(exc).__name__}: {exc}"})
        return _EndpointProbe(ok=False, url=None, capabilities={}, failures=failures)

    def _probe_failure_message(self, probe: _EndpointProbe) -> str:
        if not probe.failures:
            return (
                "Autodesk Fusion MCP endpoint was not discovered. Keep Fusion open, enable its MCP server, "
                "or set SIM_AUTODESKFUSION_MCP_URL."
            )
        tried = "; ".join(f"{item['url']} -> {item['error']}" for item in probe.failures[:5])
        return (
            "Autodesk Fusion MCP endpoint was not reachable. "
            "Fusion may be closed, MCP may be disabled, or the default port may be occupied by another process. "
            f"Tried: {tried}. Set SIM_AUTODESKFUSION_MCP_URL to the live /mcp endpoint if needed."
        )

    def _reject_legacy_transport(self, transport: Any = None) -> None:
        selected = str(transport or os.environ.get("SIM_AUTODESKFUSION_TRANSPORT", "mcp")).lower()
        if selected not in ("", "mcp", "official-mcp", "official_mcp"):
            raise RuntimeError(
                "Only Autodesk Fusion's official MCP transport is supported. "
                "The old SimFusionBridge transport was removed during the breaking rename."
            )

    def _result_path(self) -> Path:
        result_dir = self.session_dir / "results"
        result_dir.mkdir(parents=True, exist_ok=True)
        return result_dir / f"{uuid4().hex}.json"

    def _script_for_mcp(self, source: str, result_path: Path) -> str:
        prefix = (
            "import os\n"
            f"os.environ['SIM_AUTODESKFUSION_OUT'] = r'''{result_path}'''\n"
        )
        if _has_run_entrypoint(source):
            return f"{prefix}\n{source}"
        body = textwrap.indent(source.rstrip() or "pass", "    ")
        return f"{prefix}\n\ndef run(_context: str):\n{body}\n"

    def _execute_source(self, source: str, label: str = "") -> dict:
        self._reject_legacy_transport()
        result_path = self._result_path()
        probe = self._probe_endpoint(override_url=self._mcp_url)
        if not probe.ok:
            return {
                "ok": False,
                "error_code": "session_unavailable",
                "error": self._probe_failure_message(probe),
                "failures": probe.failures,
                "result_path": str(result_path),
            }

        tools = _tools_from_capabilities(probe.capabilities)
        try:
            tool_name, tool = _select_execute_tool(tools, self._execute_tool)
            arguments, field = _build_execute_arguments(tool, self._script_for_mcp(source, result_path), self._execute_field)
        except RuntimeError as exc:
            return {
                "ok": False,
                "error_code": "unsupported_operation",
                "error": str(exc),
                "endpoint": probe.url,
                "tools": _tool_names(probe.capabilities),
                "result_path": str(result_path),
            }

        try:
            call_result = self._mcp_client_factory(probe.url or DEFAULT_MCP_URL, self.timeout_s).call_tool(
                tool_name,
                arguments,
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "error_code": "execution_failed",
                "error": f"{type(exc).__name__}: {exc}",
                "endpoint": probe.url,
                "tool": tool_name,
                "result_path": str(result_path),
            }

        script_payload = _read_json_if_present(result_path)
        ok = not _tool_call_is_error(call_result)
        if isinstance(script_payload, dict) and script_payload.get("ok") is False:
            ok = False
        error = None
        if not ok:
            error = "Autodesk Fusion MCP tool reported an error"
            if isinstance(script_payload, dict):
                error = script_payload.get("error") or error

        return {
            "ok": ok,
            "endpoint": probe.url,
            "transport": "mcp",
            "tool": tool_name,
            "execute_field": field,
            "label": label,
            "mcp": call_result,
            "result": script_payload,
            "result_path": str(result_path),
            **({"error": error} if error else {}),
        }
