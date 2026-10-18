"""GUI-first HyperMesh driver for sim."""
from __future__ import annotations

import ast
import contextlib
import json
import os
import re
import shutil
import subprocess
import time
import traceback
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TextIO

from sim.driver import ConnectionInfo, Diagnostic, LintResult, RunResult, SolverInstall
from sim.runner import detect_output_errors, run_subprocess


_IMPORT_RE = re.compile(r"^\s*(import\s+hm\b|from\s+hm\b)", re.MULTILINE)
_USAGE_RE = re.compile(
    r"\bhm\.(Model|Collection|Session|FilterBy|setoption|CollectionBy|EntityBy)|"
    r"\bent\.(Node|Element|Material|Property|Component|Surface|Solid|Load)",
)
_VERSION_RE = re.compile(r"(\d{4}(?:\.\d+)*)")


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _json_default(value: object) -> str:
    return str(value)


def _candidate_roots_from_env() -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    for key in ("HYPERMESH_ROOT", "HYPERWORKS_ROOT", "ALTAIR_HOME"):
        value = os.environ.get(key)
        if value:
            out.append((Path(value), f"env:{key}"))
    return out


def _candidate_roots_from_windows_defaults() -> list[tuple[Path, str]]:
    bases: list[Path] = []
    for drive in ("C:", "D:", "E:"):
        bases.extend([
            Path(rf"{drive}\Program Files\Altair"),
            Path(rf"{drive}\Program Files (x86)\Altair"),
        ])

    out: list[tuple[Path, str]] = []
    for base in bases:
        if not base.is_dir():
            continue
        if _find_runhwx(base):
            out.append((base, f"default-path:{base}"))
        try:
            for child in sorted(base.iterdir()):
                if child.is_dir():
                    out.append((child, f"default-path:{base}"))
        except OSError:
            continue
    return out


def _candidate_roots_from_posix_defaults() -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    for base in (Path("/opt/Altair"), Path("/opt"), Path("/usr/local")):
        if not base.is_dir():
            continue
        if _find_runhwx(base):
            out.append((base, f"default-path:{base}"))
        try:
            for child in sorted(base.iterdir()):
                if child.is_dir() and "altair" in child.name.lower():
                    out.append((child, f"default-path:{base}"))
        except OSError:
            continue
    return out


def _candidate_roots_from_path() -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    for name in ("runhwx", "runhwx.exe"):
        exe = shutil.which(name)
        if not exe:
            continue
        path = Path(exe).resolve()
        for parent in path.parents:
            if _find_runhwx(parent):
                out.append((parent, f"which:{name}"))
                break
    return out


_INSTALL_FINDERS: list[Callable[[], list[tuple[Path, str]]]] = [
    _candidate_roots_from_env,
    _candidate_roots_from_windows_defaults,
    _candidate_roots_from_posix_defaults,
    _candidate_roots_from_path,
]


def _find_runhwx(root: Path) -> Path | None:
    candidates = [
        root / "hwdesktop" / "hwx" / "bin" / "win64" / "runhwx.exe",
        root / "hwdesktop" / "hwx" / "bin" / "linux64" / "runhwx",
        root / "runhwx.exe",
        root / "runhwx",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def _version_from_path(path: Path) -> str:
    for part in path.parts:
        match = _VERSION_RE.fullmatch(part)
        if match:
            return match.group(1)
    return "unknown"


def _make_install(root: Path, source: str) -> SolverInstall | None:
    exe = _find_runhwx(root)
    if exe is None:
        return None
    version = _version_from_path(root) or _version_from_path(exe)
    return SolverInstall(
        name="hypermesh",
        version=version,
        path=str(root),
        source=source,
        extra={
            "runhwx": str(exe),
            "raw_version": version,
        },
    )


def _scan_installs() -> list[SolverInstall]:
    found: dict[str, SolverInstall] = {}
    for finder in _INSTALL_FINDERS:
        try:
            candidates = finder()
        except Exception:
            continue
        for root, source in candidates:
            install = _make_install(root, source)
            if install is None:
                continue
            key = str(Path(install.path).resolve())
            found.setdefault(key, install)
    return sorted(found.values(), key=lambda inst: inst.version, reverse=True)


@dataclass
class _SessionPaths:
    root: Path
    scripts: Path
    results: Path
    logs: Path


class HyperMeshDriver:
    """Sim driver for visible HyperMesh mesh-preparation sessions."""

    GUI_PROCESS_FILTER: tuple[str, ...] = (
        "hwx",
        "hypermesh",
        "hyperworks",
    )

    def __init__(self) -> None:
        self._session_id: str | None = None
        self._install: SolverInstall | None = None
        self._proc: subprocess.Popen | None = None
        self._launch_log_handle: TextIO | None = None
        self._launch_log_path: Path | None = None
        self._ui_mode: str | None = None
        self._workspace = Path.cwd()
        self._paths = self._make_paths(self._workspace)
        self._connected_at: float | None = None
        self._run_count = 0
        self._last_run: dict | None = None
        self._launch_options: dict = {}
        self._script_submit = "auto"
        self._run_timeout_s = 300.0
        self._close_on_disconnect = False
        self._disconnected = True
        self._gui = None

    @property
    def name(self) -> str:
        return "hypermesh"

    @property
    def supports_session(self) -> bool:
        return True

    def detect(self, script: Path) -> bool:
        try:
            if script.suffix.lower() != ".py":
                return False
            text = script.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            return False
        return bool(_IMPORT_RE.search(text))

    def lint(self, script: Path) -> LintResult:
        diagnostics: list[Diagnostic] = []
        if script.suffix.lower() != ".py":
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(
                    level="error",
                    message=f"unsupported file type: {script.suffix or '(none)'}",
                )],
            )
        try:
            text = script.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(level="error", message=f"cannot read file: {exc}")],
            )
        if not text.strip():
            diagnostics.append(Diagnostic(level="error", message="script is empty"))

        has_import = bool(_IMPORT_RE.search(text))
        if not has_import:
            diagnostics.append(Diagnostic(level="warning", message="no hm import found"))

        try:
            ast.parse(text)
        except SyntaxError as exc:
            diagnostics.append(
                Diagnostic(level="error", message=f"syntax error: {exc}", line=exc.lineno)
            )

        if has_import and not _USAGE_RE.search(text):
            diagnostics.append(
                Diagnostic(level="warning", message="no obvious HyperMesh API usage found")
            )

        return LintResult(
            ok=not any(item.level == "error" for item in diagnostics),
            diagnostics=diagnostics,
        )

    def connect(self) -> ConnectionInfo:
        installs = self.detect_installed()
        if not installs:
            return ConnectionInfo(
                solver=self.name,
                version=None,
                status="not_installed",
                message="No HyperMesh installation was detected on this host.",
            )
        top = installs[0]
        return ConnectionInfo(
            solver=self.name,
            version=top.extra.get("raw_version", top.version),
            solver_version=top.version,
            status="ok",
            message=f"HyperMesh installation detected at {top.path}",
        )

    def detect_installed(self) -> list[SolverInstall]:
        return _scan_installs()

    def parse_output(self, stdout: str) -> dict:
        for line in reversed(stdout.strip().splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
        return {}

    def run_file(self, script: Path) -> RunResult:
        if script.suffix.lower() != ".py":
            raise RuntimeError(f"HyperMesh accepts .py scripts, got {script.suffix}")
        install = self._resolve_install()
        command = self._command(install, script=script)
        return run_subprocess(command, script=script, solver=self.name)

    def launch(
        self,
        mode: str = "meshing",
        ui_mode: str = "gui",
        processors: int = 1,
        workspace: str | None = None,
        cwd: str | None = None,
        hypermesh_root: str | None = None,
        executable: str | None = None,
        script_submit: str = "auto",
        run_timeout_s: float = 300,
        close_on_disconnect: bool = False,
        language: str = "en",
        **kwargs,
    ) -> dict:
        if ui_mode != "gui":
            raise RuntimeError("HyperMesh sim sessions require ui_mode=gui.")

        submit_mode = script_submit.strip().lower()
        if submit_mode not in {"auto", "manual"}:
            raise RuntimeError("script_submit must be 'auto' or 'manual'.")

        self._session_id = f"hm-{uuid.uuid4().hex[:8]}"
        self._workspace = Path(workspace or cwd or Path.cwd()).resolve()
        self._paths = self._make_paths(self._workspace)
        self._ensure_paths()
        self._install = self._resolve_install(
            hypermesh_root=hypermesh_root,
            executable=executable,
        )
        self._ui_mode = ui_mode
        self._connected_at = time.time()
        self._run_count = 0
        self._last_run = None
        self._script_submit = submit_mode
        self._run_timeout_s = float(run_timeout_s)
        self._close_on_disconnect = _as_bool(close_on_disconnect)
        self._disconnected = False
        self._launch_options = {
            "mode": mode,
            "ui_mode": ui_mode,
            "processors": processors,
            "workspace": str(self._workspace),
            "script_submit": self._script_submit,
            "run_timeout_s": self._run_timeout_s,
            "close_on_disconnect": self._close_on_disconnect,
            "language": language,
            **kwargs,
        }

        self._launch_log_path, self._launch_log_handle = self._open_log("hypermesh-launch")
        self._proc = self._start_gui_process(
            self._command(self._install, script=None, language=language),
            self._launch_log_handle,
        )

        from sim.gui import GuiController  # noqa: PLC0415
        self._gui = GuiController(
            process_name_substrings=self.GUI_PROCESS_FILTER,
            workdir=str(self._paths.root),
        )

        return {
            "ok": True,
            "session_id": self._session_id,
            "mode": "gui",
            "source": "launch",
            "ui_mode": self._ui_mode,
            "ui_capabilities": self._ui_capabilities(),
            "workspace": str(self._workspace),
            "install_path": self._install.path,
            "process_pid": getattr(self._proc, "pid", None),
            "launch_log_path": str(self._launch_log_path) if self._launch_log_path else None,
            "launch_options": dict(self._launch_options),
            "health": self.health(),
        }

    def run(
        self,
        code: str,
        label: str = "hypermesh-snippet",
        timeout_s: float | None = None,
    ) -> dict:
        if self._session_id is None or self._disconnected:
            return self._run_failure(
                label=label,
                code="hypermesh.session.disconnected",
                message="No active HyperMesh session.",
                started_at=time.time(),
            )

        run_id = f"run-{uuid.uuid4().hex[:8]}"
        started_at = time.time()
        timeout = float(timeout_s if timeout_s is not None else self._run_timeout_s)
        script_path = self._paths.scripts / f"{run_id}.py"
        result_path = self._paths.results / f"{run_id}.json"
        log_path = self._paths.logs / f"{run_id}.log"
        script_path.write_text(
            self._wrap_snippet(code, result_path=result_path),
            encoding="utf-8",
        )

        if self._script_submit == "manual":
            record = self._run_failure(
                label=label,
                code="hypermesh.script.manual_submission",
                message="Script was written for manual submission.",
                started_at=started_at,
                run_id=run_id,
                script_path=script_path,
                result_path=result_path,
            )
            self._last_run = record
            return record

        try:
            self._submit_script(script_path, log_path)
        except Exception as exc:  # noqa: BLE001 - process failures vary by host
            record = self._run_failure(
                label=label,
                code="hypermesh.script.submit_failed",
                message=f"Could not submit script: {exc}",
                started_at=started_at,
                run_id=run_id,
                script_path=script_path,
                result_path=result_path,
            )
            self._last_run = record
            return record

        payload = self._wait_for_result(result_path, timeout_s=timeout)
        elapsed = round(time.time() - started_at, 4)
        self._run_count += 1

        if payload is None:
            record = {
                "run_id": run_id,
                "ok": False,
                "label": label,
                "stdout": "",
                "stderr": "",
                "error": f"Timed out waiting for HyperMesh result after {timeout:g}s.",
                "error_code": "hypermesh.script.timeout",
                "message": f"Timed out waiting for result after {timeout:g}s.",
                "result": None,
                "elapsed_s": elapsed,
                "script_path": str(script_path),
                "result_path": str(result_path),
                "log_path": str(log_path),
                "diagnostics": [self._diagnostic(
                    "error",
                    "hypermesh.script.timeout",
                    f"No result file appeared within {timeout:g}s.",
                )],
                "artifacts": self._artifacts([script_path, log_path]),
                "health": self.health(),
            }
            self._last_run = record
            return record

        ok = bool(payload.get("ok", False))
        stdout = str(payload.get("stdout") or "")
        stderr = str(payload.get("stderr") or "")
        error_text = payload.get("error")
        diagnostics = []
        if not ok:
            diagnostics.append(self._diagnostic(
                "error",
                "hypermesh.script.failed",
                str(error_text or "HyperMesh snippet failed."),
            ))
        for detected in detect_output_errors(stdout, stderr):
            diagnostics.append(self._diagnostic("warning", "hypermesh.output.warning", detected))

        record = {
            "run_id": run_id,
            "ok": ok,
            "label": label,
            "stdout": stdout,
            "stderr": stderr,
            "error": error_text,
            "result": payload.get("result"),
            "elapsed_s": elapsed,
            "script_path": str(script_path),
            "result_path": str(result_path),
            "log_path": str(log_path),
            "diagnostics": diagnostics,
            "artifacts": self._artifacts([script_path, result_path, log_path]),
            "health": self.health(),
        }
        self._last_run = record
        return record

    def disconnect(self) -> dict:
        reason = self.health()
        if self._close_on_disconnect and self._proc is not None and self._proc.poll() is None:
            with contextlib.suppress(Exception):
                self._proc.terminate()
                self._proc.wait(timeout=10)
        self._close_log_handles()
        self._session_id = None
        self._connected_at = None
        self._disconnected = True
        self._ui_mode = None
        self._gui = None
        self._last_run = None
        return {
            "ok": True,
            "disconnected": True,
            "previous_health": reason,
        }

    def query(self, name: str) -> dict:
        if name in {"health", "session.health"}:
            return self.health()
        if name in {"ui.modes", "session.ui_modes"}:
            return {
                "ok": True,
                "modes": {
                    "gui": "Visible desktop session for human-agent mesh collaboration.",
                },
                "default": "gui",
            }
        if name in {"hypermesh.session.identity", "session.identity"}:
            return self._identity()
        if name in {"hypermesh.workspace.files", "workspace.files"}:
            return {
                "ok": True,
                "workspace": str(self._workspace),
                "files": self._workspace_files(),
            }
        return {"ok": False, "error": f"unknown inspect target: {name}"}

    def health(self) -> dict:
        proc_returncode = self._proc.poll() if self._proc is not None else None
        proc_running = self._proc is not None and proc_returncode is None
        windows = self._list_windows()
        window_seen = bool(windows)
        connected = (
            self._session_id is not None
            and not self._disconnected
            and (proc_running or window_seen or self._proc is not None)
        )
        code = "hypermesh.session.connected" if connected else "hypermesh.session.disconnected"
        message = "HyperMesh session is connected." if connected else "No active HyperMesh session."
        if self._proc is not None and proc_returncode not in (None, 0) and not window_seen:
            code = "hypermesh.process.exited"
            message = f"HyperMesh launcher exited with return code {proc_returncode}."
            connected = False

        return {
            "ok": connected,
            "connected": connected,
            "code": code,
            "message": message,
            "session_id": self._session_id,
            "ui_mode": self._ui_mode,
            "ui_capabilities": self._ui_capabilities(),
            "workspace": str(self._workspace),
            "process_pid": getattr(self._proc, "pid", None),
            "process_running": proc_running,
            "process_returncode": proc_returncode,
            "launch_log_path": str(self._launch_log_path) if self._launch_log_path else None,
            "run_count": self._run_count,
            "last_run_ok": self._last_run.get("ok") if self._last_run else None,
            "windows": windows,
        }

    def _resolve_install(
        self,
        *,
        hypermesh_root: str | None = None,
        executable: str | None = None,
    ) -> SolverInstall:
        if executable:
            exe = Path(executable).resolve()
            if not exe.is_file():
                raise RuntimeError(f"HyperMesh launcher not found: {exe}")
            root = exe.parent
            return SolverInstall(
                name=self.name,
                version=_version_from_path(exe),
                path=str(root),
                source="driver-option:executable",
                extra={"runhwx": str(exe), "raw_version": _version_from_path(exe)},
            )
        if hypermesh_root:
            install = _make_install(Path(hypermesh_root), "driver-option:hypermesh_root")
            if install is None:
                raise RuntimeError(f"HyperMesh launcher not found under {hypermesh_root}")
            return install
        installs = self.detect_installed()
        if not installs:
            raise RuntimeError("No HyperMesh installation was detected on this host.")
        return installs[0]

    def _command(
        self,
        install: SolverInstall,
        *,
        script: Path | None,
        language: str = "en",
    ) -> list[str]:
        exe = str(install.extra["runhwx"])
        command = [
            exe,
            "-client", "HyperWorksDesktop",
            "-plugin", "HyperworksLauncher",
            "-profile", "HyperworksLauncher",
            "-l", language,
            "-startwith", "HyperMesh",
        ]
        if script is not None:
            command.extend(["-f", str(script)])
        return command

    def _start_gui_process(self, command: list[str], log_handle: TextIO) -> subprocess.Popen:
        return subprocess.Popen(
            command,
            cwd=str(self._workspace),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
        )

    def _submit_script(self, script_path: Path, log_path: Path) -> subprocess.Popen:
        if self._install is None:
            raise RuntimeError("session has no resolved installation")
        log_handle = log_path.open("a", encoding="utf-8", errors="replace")
        return subprocess.Popen(
            self._command(self._install, script=script_path),
            cwd=str(self._workspace),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
        )

    def _wrap_snippet(self, code: str, *, result_path: Path) -> str:
        return f"""# Generated by sim-plugin-hypermesh.
import contextlib
import io
import json
import traceback

_sim_stdout = io.StringIO()
_sim_stderr = io.StringIO()
_result = None
try:
    with contextlib.redirect_stdout(_sim_stdout), contextlib.redirect_stderr(_sim_stderr):
        exec({code!r}, globals(), globals())
    _payload = {{
        "ok": True,
        "stdout": _sim_stdout.getvalue(),
        "stderr": _sim_stderr.getvalue(),
        "result": _result,
    }}
except BaseException as _exc:
    _payload = {{
        "ok": False,
        "stdout": _sim_stdout.getvalue(),
        "stderr": _sim_stderr.getvalue(),
        "error": "".join(traceback.format_exception(type(_exc), _exc, _exc.__traceback__)),
        "exception_type": type(_exc).__name__,
        "result": _result,
    }}

with open({str(result_path)!r}, "w", encoding="utf-8") as _f:
    json.dump(_payload, _f, default=str)
print(json.dumps(_payload, default=str))
"""

    def _wait_for_result(self, path: Path, *, timeout_s: float) -> dict | None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if path.is_file():
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    time.sleep(0.2)
                    continue
            time.sleep(0.2)
        return None

    def _make_paths(self, workspace: Path) -> _SessionPaths:
        root = workspace / ".sim" / "hypermesh"
        return _SessionPaths(
            root=root,
            scripts=root / "scripts",
            results=root / "results",
            logs=root / "logs",
        )

    def _ensure_paths(self) -> None:
        for path in (self._workspace, self._paths.root, self._paths.scripts,
                     self._paths.results, self._paths.logs):
            path.mkdir(parents=True, exist_ok=True)

    def _open_log(self, stem: str) -> tuple[Path, TextIO]:
        self._ensure_paths()
        suffix = self._session_id or time.strftime("%Y%m%d-%H%M%S")
        path = self._paths.logs / f"{stem}-{suffix}.log"
        return path, path.open("a", encoding="utf-8", errors="replace")

    def _close_log_handles(self) -> None:
        if self._launch_log_handle is not None:
            with contextlib.suppress(Exception):
                self._launch_log_handle.close()
            self._launch_log_handle = None

    def _ui_capabilities(self) -> dict:
        return {
            "desktop_visible": self._ui_mode == "gui",
            "model_builder_live": self._ui_mode == "gui",
            "screenshot_source": "codex-desktop-or-sim-remote",
            "snippet_submission": self._script_submit,
        }

    def _identity(self) -> dict:
        install = self._install
        return {
            "ok": self._session_id is not None and not self._disconnected,
            "session_id": self._session_id,
            "workspace": str(self._workspace),
            "install_path": install.path if install else None,
            "version": install.version if install else None,
            "executable": install.extra.get("runhwx") if install else None,
            "process_pid": getattr(self._proc, "pid", None),
            "launch_options": dict(self._launch_options),
        }

    def _list_windows(self) -> list[dict]:
        if self._gui is None:
            return []
        try:
            result = self._gui.list_windows()
        except Exception:
            return []
        if not result.get("ok"):
            return []
        return list(result.get("windows") or [])

    def _workspace_files(self, limit: int = 200) -> list[dict]:
        if not self._workspace.is_dir():
            return []
        files: list[dict] = []
        try:
            iterator = self._workspace.rglob("*")
            for path in iterator:
                if not path.is_file():
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                files.append({
                    "path": str(path.relative_to(self._workspace)).replace("\\", "/"),
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(
                        stat.st_mtime, tz=timezone.utc
                    ).isoformat(),
                })
                if len(files) >= limit:
                    break
        except OSError:
            return files
        return sorted(files, key=lambda item: item["path"])

    def _artifacts(self, paths: list[Path]) -> list[dict]:
        out: list[dict] = []
        for path in paths:
            if not path.exists():
                continue
            out.append({
                "path": str(path),
                "kind": "file",
                "size": path.stat().st_size,
            })
        return out

    def _diagnostic(self, severity: str, code: str, message: str) -> dict:
        return {
            "severity": severity,
            "code": code,
            "message": message[:500],
        }

    def _run_failure(
        self,
        *,
        label: str,
        code: str,
        message: str,
        started_at: float,
        run_id: str | None = None,
        script_path: Path | None = None,
        result_path: Path | None = None,
    ) -> dict:
        elapsed = round(time.time() - started_at, 4)
        record = {
            "run_id": run_id or f"run-{uuid.uuid4().hex[:8]}",
            "ok": False,
            "label": label,
            "stdout": "",
            "stderr": "",
            "error": message,
            "error_code": code,
            "message": message,
            "result": None,
            "elapsed_s": elapsed,
            "diagnostics": [self._diagnostic("error", code, message)],
            "artifacts": self._artifacts([
                path for path in (script_path, result_path) if path is not None
            ]),
            "health": self.health(),
        }
        if script_path is not None:
            record["script_path"] = str(script_path)
        if result_path is not None:
            record["result_path"] = str(result_path)
        return record

    def __del__(self) -> None:  # pragma: no cover - best-effort cleanup
        self._close_log_handles()
