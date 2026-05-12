"""Autodesk Fusion 360 driver for sim.

Fusion exposes its Python API inside the Fusion GUI process. This driver stays
import-safe on hosts without Fusion by doing host discovery with the stdlib and
communicating with a small Fusion-side add-in bridge through files.
"""
from __future__ import annotations

import ast
from datetime import datetime, timezone
import json
import os
from importlib.resources import files
import re
import shutil
import time
from pathlib import Path
from uuid import uuid4

from sim.driver import ConnectionInfo, Diagnostic, LintResult, RunResult, SolverInstall


_SCRIPT_MARKERS = ("import adsk", "from adsk", "adsk.core", "adsk.fusion", "adsk.sim")
_VERSION_RE = re.compile(r"Fusion360_([^_]+)_(?:addins_to_load|cached_addins)\.xml$", re.IGNORECASE)
_BRIDGE_STALE_AFTER_S = 5.0
_DEFAULT_TIMEOUT_S = 120.0


def _default_api_dir() -> Path:
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "Autodesk" / "Autodesk Fusion 360" / "API"
    return Path.home() / "Library" / "Application Support" / "Autodesk" / "Autodesk Fusion 360" / "API"


def _default_session_dir() -> Path:
    return Path(os.environ.get("SIM_FUSION360_SESSION_DIR", Path.home() / ".sim" / "fusion360"))


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
    for var in ("SIM_FUSION360_EXE", "FUSION360_EXE"):
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
        name="fusion360",
        version=version,
        path=str(exe.parent),
        source=source,
        extra={
            "exe": str(exe),
            "api_dir": str(api_dir),
            "bridge_dir": str(api_dir / "AddIns" / "SimFusionBridge"),
        },
    )


class Fusion360Driver:
    """Fusion 360 driver backed by a visible-session add-in bridge."""

    def __init__(
        self,
        *,
        session_dir: str | os.PathLike[str] | None = None,
        api_dir: str | os.PathLike[str] | None = None,
        timeout_s: float | None = None,
    ) -> None:
        self.session_dir = Path(session_dir) if session_dir is not None else _default_session_dir()
        self.api_dir = Path(api_dir) if api_dir is not None else _default_api_dir()
        self.timeout_s = timeout_s if timeout_s is not None else float(
            os.environ.get("SIM_FUSION360_TIMEOUT_S", _DEFAULT_TIMEOUT_S)
        )
        self._session_id: str | None = None

    @property
    def name(self) -> str:
        return "fusion360"

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
                diagnostics=[Diagnostic(level="error", message="Fusion 360 scripts must be Python .py files")],
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
        if not installs:
            return ConnectionInfo(
                solver=self.name,
                version=None,
                status="not_installed",
                message="Autodesk Fusion 360 not found. Set SIM_FUSION360_EXE or install Fusion.",
            )
        top = installs[0]
        bridge = "bridge running" if self._bridge_is_running() else "bridge not running"
        return ConnectionInfo(
            solver=self.name,
            version=top.version,
            status="ok",
            message=f"Fusion 360 {top.version} at {top.extra.get('exe', top.path)} ({bridge})",
            solver_version=top.version,
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
        for line in reversed(stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        return {}

    def run_file(self, script: Path) -> RunResult:
        if script.suffix.lower() != ".py":
            raise RuntimeError(f"fusion360 driver only accepts .py scripts (got {script.suffix})")
        lint = self.lint(script)
        if not lint.ok:
            messages = "; ".join(d.message for d in lint.diagnostics)
            raise RuntimeError(f"Fusion 360 script failed lint: {messages}")
        if not self._bridge_is_running():
            raise RuntimeError(
                "Fusion 360 bridge is not running. Call launch(), then run SimFusionBridge once from Fusion's Scripts and Add-Ins dialog."
            )

        started = time.time()
        result_path = self._enqueue({
            "kind": "script_file",
            "script": str(Path(script).resolve()),
            "env": {},
        })
        result = self._wait_for_result(result_path, self.timeout_s)
        stdout = json.dumps(result, separators=(",", ":"))
        ok = bool(result.get("ok", False))
        return RunResult(
            exit_code=0 if ok else 1,
            stdout=stdout,
            stderr=result.get("stderr", ""),
            duration_s=round(time.time() - started, 3),
            script=str(Path(script).resolve()),
            solver=self.name,
            timestamp=datetime.now(timezone.utc).isoformat(),
            errors=[] if ok else [result.get("error", "Fusion bridge command failed")],
            artifacts=[{"path": str(result_path), "kind": "json", "role": "bridge-result"}],
        )

    def launch(self, **kwargs) -> dict:
        bridge_dir = self.install_bridge()
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._session_id = self._session_id or uuid4().hex
        if self._bridge_is_running():
            return {
                "ok": True,
                "session_id": self._session_id,
                "bridge_dir": str(bridge_dir),
                "message": "Fusion 360 bridge is running.",
            }
        return {
            "ok": True,
            "session_id": self._session_id,
            "bridge_dir": str(bridge_dir),
            "requires_user_action": True,
            "message": "Open Fusion Scripts and Add-Ins, select SimFusionBridge, and press Run.",
        }

    def run(self, code: str, label: str = "") -> dict:
        if not self._bridge_is_running():
            return {
                "ok": False,
                "error_code": "session_unavailable",
                "message": "Fusion 360 bridge is not running. Run launch() and start SimFusionBridge in Fusion.",
            }
        result_path = self._enqueue({"kind": "code", "code": code, "label": label, "env": {}})
        return self._wait_for_result(result_path, self.timeout_s)

    def disconnect(self) -> dict:
        self._session_id = None
        return {"ok": True, "disconnected": True}

    def install_bridge(self, api_dir: str | os.PathLike[str] | None = None) -> Path:
        api_root = Path(api_dir) if api_dir is not None else self.api_dir
        bridge_dir = api_root / "AddIns" / "SimFusionBridge"
        bridge_dir.mkdir(parents=True, exist_ok=True)
        source_dir = files("sim_plugin_fusion360").joinpath("bridge")
        for name in ("SimFusionBridge.py", "SimFusionBridge.manifest"):
            source = source_dir.joinpath(name)
            target = bridge_dir / name
            target.write_bytes(source.read_bytes())
        return bridge_dir

    def _status_path(self) -> Path:
        return self.session_dir / "bridge_status.json"

    def _bridge_status(self) -> dict | None:
        try:
            return json.loads(self._status_path().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _bridge_is_running(self) -> bool:
        status = self._bridge_status()
        if not status or status.get("status") != "running":
            return False
        heartbeat = status.get("heartbeat")
        if not isinstance(heartbeat, (int, float)):
            return False
        return time.time() - float(heartbeat) <= _BRIDGE_STALE_AFTER_S

    def _enqueue(self, command: dict) -> Path:
        command_id = uuid4().hex
        queue_dir = self.session_dir / "queue"
        result_dir = self.session_dir / "results"
        queue_dir.mkdir(parents=True, exist_ok=True)
        result_dir.mkdir(parents=True, exist_ok=True)
        result_path = result_dir / f"{command_id}.json"
        command_path = queue_dir / f"{command_id}.json"
        payload = {
            "id": command_id,
            "result": str(result_path),
            "command_path": str(command_path),
            **command,
        }
        env = dict(payload.get("env") or {})
        env.setdefault("SIM_FUSION360_OUT", str(result_path))
        payload["env"] = env
        command_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return result_path

    def _wait_for_result(self, result_path: Path, timeout_s: float) -> dict:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if result_path.exists():
                return json.loads(result_path.read_text(encoding="utf-8"))
            time.sleep(0.1)
        raise TimeoutError(f"Fusion bridge did not produce a result within {timeout_s:.1f}s: {result_path}")
