"""Abaqus driver for sim.

Abaqus is a commercial FEA solver by Dassault Systemes SIMULIA. Execution
is via the ``abaqus`` command-line tool:
  - Input decks (.inp): ``abaqus job=<name> input=<file> interactive``
  - Python scripts (.py): ``abaqus cae noGUI=<file>``

This driver is pure subprocess — it never imports Abaqus internals (which
live in Abaqus's own embedded Python, not the system Python). Detection
scans for the ``abaqus.bat`` / ``abq20XX.bat`` launcher in standard
SIMULIA install paths.
"""
from __future__ import annotations

import ast
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sim.driver import ConnectionInfo, Diagnostic, LintResult, RunResult, SolverInstall

# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------

_ABAQUS_IMPORT_RE = re.compile(
    r"^\s*(from\s+abaqus\b|from\s+abaqusConstants\b|import\s+abaqus\b)",
    re.MULTILINE,
)

_INP_KEYWORD_RE = re.compile(r"^\*\w+", re.MULTILINE)

_EXPLICIT_LAUNCHER_ENV_VARS = (
    "SIM_ABAQUS_COMMAND",
    "ABAQUS_COMMAND",
    "ABAQUS_BAT_PATH",
)

_NOT_INSTALLED_HINT = (
    "No Abaqus installation detected on this host. The driver looks for "
    "abq20XX.bat/abaqus.bat in standard SIMULIA Commands directories and "
    "on PATH. If Abaqus is installed elsewhere, set SIM_ABAQUS_COMMAND to "
    "the full launcher path, e.g. C:\\SIMULIA\\Commands\\abq2026.bat."
)

_ARTIFACT_EXTENSIONS = {
    ".cae",
    ".com",
    ".dat",
    ".jnl",
    ".log",
    ".msg",
    ".odb",
    ".prt",
    ".sim",
    ".sta",
}


def _find_abaqus_bat(commands_dir: Path) -> Path | None:
    """Return the highest-version abqNNNN.bat in a Commands directory."""
    if not commands_dir.is_dir():
        return None
    bats = sorted(commands_dir.glob("abq*.bat"), reverse=True)
    for bat in bats:
        if bat.name.startswith("abq") and bat.name != "abq_cae_open.bat" and bat.name != "abq_odb_open.bat":
            return bat
    return None


def _version_from_bat_name(bat: Path) -> str | None:
    """Extract version year from bat name: abq2026.bat -> '2026'."""
    m = re.search(r"abq(\d{4})", bat.name)
    return m.group(1) if m else None


def _version_from_info(abaqus_cmd: str) -> str | None:
    """Run ``abaqus information=release`` and parse version string."""
    try:
        result = subprocess.run(
            [abaqus_cmd, "information=release"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    # Parse "Abaqus 2026" from output
    m = re.search(r"Abaqus\s+(\d{4})", result.stdout)
    return m.group(1) if m else None


def _resolve_explicit_launcher(value: str) -> Path | None:
    """Resolve an explicit launcher env var to a concrete executable path."""
    raw = value.strip().strip("\"'")
    if not raw:
        return None

    p = Path(raw)
    if p.is_file():
        return p
    if p.is_dir():
        return _find_abaqus_bat(p) or ((p / "abaqus.bat") if (p / "abaqus.bat").is_file() else None)

    found = shutil.which(raw)
    return Path(found) if found else None


def _explicit_installs_from_env() -> list[SolverInstall]:
    """Honor user-provided launcher paths before probing default locations."""
    installs: list[SolverInstall] = []
    seen: set[str] = set()
    for var in _EXPLICIT_LAUNCHER_ENV_VARS:
        val = os.environ.get(var)
        if not val:
            continue
        launcher = _resolve_explicit_launcher(val)
        if launcher is None:
            continue
        key = str(launcher.resolve())
        if key in seen:
            continue
        seen.add(key)
        version = _version_from_bat_name(launcher) or _version_from_info(str(launcher)) or "unknown"
        installs.append(SolverInstall(
            name="abaqus",
            version=version,
            path=str(launcher.parent),
            source=f"env:{var}",
            extra={"bat": str(launcher)},
        ))
    return installs


# ---------------------------------------------------------------------------
# Install-dir finders (strategy chain — append new finders, don't modify)
# ---------------------------------------------------------------------------


def _candidates_from_env() -> list[tuple[Path, str]]:
    """Check SIMULIA_HOME and ABAQUS_BAT_PATH env vars."""
    out: list[tuple[Path, str]] = []
    for var in ("SIMULIA_HOME", "ABAQUS_BAT_PATH"):
        val = os.environ.get(var)
        if val:
            p = Path(val)
            if p.is_file() and p.suffix == ".bat":
                out.append((p.parent, f"env:{var}"))
            elif p.is_dir():
                commands = p / "Commands"
                if commands.is_dir():
                    out.append((commands, f"env:{var}"))
                elif (p / "abaqus.bat").is_file() or _find_abaqus_bat(p):
                    out.append((p, f"env:{var}"))
    return out


def _candidates_from_defaults() -> list[tuple[Path, str]]:
    """Scan standard SIMULIA install directories on Windows."""
    bases = []
    for drive in ("C", "D", "E"):
        bases.extend([
            Path(f"{drive}:/Program Files (x86)/Dassault Systemes/SIMULIA/Commands"),
            Path(f"{drive}:/Program Files/Dassault Systemes/SIMULIA/Commands"),
            Path(f"{drive}:/SIMULIA/Commands"),
            Path(f"{drive}:/Program Files (x86)/SIMULIA/Commands"),
        ])
    out: list[tuple[Path, str]] = []
    for base in bases:
        if base.is_dir():
            out.append((base, f"default-path:{base}"))
    return out


def _candidates_from_path() -> list[tuple[Path, str]]:
    """``which abaqus`` — last-resort PATH probe."""
    out: list[tuple[Path, str]] = []
    abaqus_bin = shutil.which("abaqus")
    if abaqus_bin:
        p = Path(abaqus_bin).resolve()
        out.append((p.parent, "which:abaqus"))
    return out


_INSTALL_FINDERS = [
    _candidates_from_env,
    _candidates_from_defaults,
    _candidates_from_path,
]


def _scan_abaqus_installs() -> list[SolverInstall]:
    """Find every Abaqus installation on this host. Pure stdlib."""
    found: dict[str, SolverInstall] = {}
    explicit_installs = _explicit_installs_from_env()
    explicit_keys: list[str] = []

    for install in explicit_installs:
        bat = install.extra.get("bat")
        if bat:
            key = str(Path(bat).resolve())
            found[key] = install
            explicit_keys.append(key)

    for finder in _INSTALL_FINDERS:
        try:
            candidates = finder()
        except Exception:
            continue
        for commands_dir, source in candidates:
            bat = _find_abaqus_bat(commands_dir)
            if bat is None:
                # Try abaqus.bat directly
                ab = commands_dir / "abaqus.bat"
                if ab.is_file():
                    bat = ab
                else:
                    continue

            key = str(bat.resolve())
            if key in found:
                continue

            version = _version_from_bat_name(bat) or "unknown"
            found[key] = SolverInstall(
                name="abaqus",
                version=version,
                path=str(commands_dir),
                source=source,
                extra={"bat": str(bat)},
            )

    explicit = [found[key] for key in explicit_keys if key in found]
    discovered = [
        install
        for key, install in found.items()
        if key not in set(explicit_keys)
    ]
    return explicit + sorted(discovered, key=lambda i: i.version, reverse=True)


# ---------------------------------------------------------------------------
# Driver class
# ---------------------------------------------------------------------------


class AbaqusDriver:
    """Sim driver for Dassault Systemes SIMULIA Abaqus.

    DriverProtocol surface:
        name, detect, lint, connect, parse_output, run_file, detect_installed
    """

    def __init__(self):
        self._session_id: str | None = None
        self._session_workspace: Path | None = None
        self._session_cae: Path | None = None
        self._session_ui_mode: str = "no_gui"
        self._session_mode: str = "cae"
        self._session_backend: str = "file"
        self._abaqus_bat: str | None = None
        self._solver_version: str | None = None
        self._run_count = 0
        self._last_result: dict | None = None
        self._last_run_started_at: float | None = None
        self._snippet_timeout_s = 600.0
        self._launch_timeout_s = 120.0
        self._bridge_proc: subprocess.Popen[str] | None = None
        self._bridge_host: str | None = None
        self._bridge_port: int | None = None
        self._bridge_token: str | None = None
        self._bridge_stdout_handle = None
        self._bridge_stderr_handle = None
        self._bridge_stdout_path: Path | None = None
        self._bridge_stderr_path: Path | None = None

    def _persistence(self) -> str:
        return "live-bridge" if self._session_backend == "bridge" else "file-backed-cae"

    def _bridge_running(self) -> bool:
        return self._bridge_proc is not None and self._bridge_proc.poll() is None

    def _ui_capabilities(self) -> dict:
        visible = self._session_ui_mode in {"gui", "desktop", "visible"}
        return {
            "requested_ui_mode": self._session_ui_mode,
            "effective_ui_mode": "gui" if visible else "no_gui",
            "screenshot_expected": False,
            "desktop_inspection": "transient-script" if visible else "unavailable",
            "model_builder_live": False,
            "notes": (
                "Abaqus CAE script mode may create a transient visible window, "
                "but this plugin does not maintain a persistent Desktop session."
                if visible
                else "Abaqus runs through noGUI subprocess or bridge execution."
            ),
        }

    def health(self) -> dict:
        """Best-effort authoring-session health for public inspect output."""
        session_exists = self._session_id is not None
        bridge_running = self._bridge_running()
        if not session_exists:
            connected = False
            code = "abaqus.session.disconnected"
            message = "Abaqus CAE session is not connected"
        elif self._session_backend == "bridge" and not bridge_running:
            connected = False
            code = "abaqus.bridge.not_running"
            message = "Abaqus bridge backend is not running"
        else:
            connected = True
            code = "abaqus.session.connected"
            message = "Abaqus CAE session is connected"

        return {
            "ok": connected,
            "connected": connected,
            "code": code,
            "message": message,
            "session_id": self._session_id,
            "solver_version": self._solver_version,
            "mode": self._session_mode,
            "ui_mode": self._session_ui_mode,
            "backend": self._session_backend,
            "persistence": self._persistence() if session_exists else None,
            "workspace": str(self._session_workspace) if self._session_workspace else None,
            "cae_path": str(self._session_cae) if self._session_cae else None,
            "run_count": self._run_count,
            "last_ok": None if self._last_result is None else self._last_result.get("ok"),
            "snippet_timeout_s": self._snippet_timeout_s,
            "ui_capabilities": self._ui_capabilities(),
            "bridge": {
                "running": bridge_running,
                "host": self._bridge_host,
                "port": self._bridge_port,
                "pid": None if self._bridge_proc is None else self._bridge_proc.pid,
            } if self._session_backend == "bridge" else None,
        }

    @property
    def name(self) -> str:
        return "abaqus"

    @property
    def supports_session(self) -> bool:
        return True

    # -- detect ---------------------------------------------------------------

    def detect(self, script: Path) -> bool:
        """Detect Abaqus scripts: .inp files or .py with Abaqus imports."""
        try:
            if script.suffix.lower() == ".inp":
                text = script.read_text(encoding="utf-8", errors="replace")
                return bool(_INP_KEYWORD_RE.search(text))
            if script.suffix.lower() == ".py":
                text = script.read_text(encoding="utf-8", errors="replace")
                return bool(_ABAQUS_IMPORT_RE.search(text))
        except (OSError, UnicodeDecodeError):
            pass
        return False

    # -- lint -----------------------------------------------------------------

    def lint(self, script: Path) -> LintResult:
        """Validate an Abaqus script or input deck."""
        diagnostics: list[Diagnostic] = []
        suffix = script.suffix.lower()

        try:
            text = script.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(level="error", message=f"Cannot read file: {e}")],
            )

        if suffix == ".inp":
            return self._lint_inp(text, diagnostics)
        elif suffix == ".py":
            return self._lint_py(text, diagnostics)
        else:
            diagnostics.append(
                Diagnostic(
                    level="error",
                    message=f"Unsupported file type: {suffix} (expected .inp or .py)",
                )
            )
            return LintResult(ok=False, diagnostics=diagnostics)

    def _lint_inp(self, text: str, diagnostics: list[Diagnostic]) -> LintResult:
        """Lint an Abaqus .inp input deck."""
        has_keyword = bool(_INP_KEYWORD_RE.search(text))
        if not has_keyword:
            diagnostics.append(
                Diagnostic(level="error", message="No Abaqus keywords found (expected *KEYWORD lines)")
            )

        has_step = bool(re.search(r"^\*STEP", text, re.MULTILINE | re.IGNORECASE))
        if not has_step:
            diagnostics.append(
                Diagnostic(
                    level="warning",
                    message="No *STEP keyword found — input deck may not define an analysis step",
                )
            )

        ok = not any(d.level == "error" for d in diagnostics)
        return LintResult(ok=ok, diagnostics=diagnostics)

    def _lint_py(self, text: str, diagnostics: list[Diagnostic]) -> LintResult:
        """Lint an Abaqus Python script."""
        has_import = bool(_ABAQUS_IMPORT_RE.search(text))
        if not has_import:
            diagnostics.append(
                Diagnostic(level="error", message="No Abaqus import found (expected 'from abaqus import *')")
            )

        try:
            ast.parse(text)
        except SyntaxError as e:
            diagnostics.append(
                Diagnostic(level="error", message=f"Syntax error: {e}", line=e.lineno)
            )

        ok = not any(d.level == "error" for d in diagnostics)
        return LintResult(ok=ok, diagnostics=diagnostics)

    # -- connect / detect_installed -------------------------------------------

    def connect(self) -> ConnectionInfo:
        """Lightweight availability check via detect_installed."""
        installs = self.detect_installed()
        if not installs:
            return ConnectionInfo(
                solver="abaqus",
                version=None,
                status="not_installed",
                message=_NOT_INSTALLED_HINT,
            )
        top = installs[0]
        return ConnectionInfo(
            solver="abaqus",
            version=top.version,
            status="ok",
            message=f"Abaqus {top.version} at {top.path}",
            solver_version=top.version,
        )

    def detect_installed(self) -> list[SolverInstall]:
        """Scan for Abaqus installations. Pure stdlib, no SDK import."""
        return _scan_abaqus_installs()

    # -- parse_output ---------------------------------------------------------

    def parse_output(self, stdout: str) -> dict:
        """Extract last JSON object from stdout (driver convention)."""
        for line in reversed(stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        return {}

    # -- output inspection ----------------------------------------------------

    def _collect_artifacts(
        self,
        work_dir: Path,
        stem: str | None = None,
        modified_since: float | None = None,
    ) -> list[dict]:
        """Return Abaqus artifacts in a workspace without opening binary files."""
        artifacts: list[dict] = []
        try:
            candidates = list(work_dir.iterdir())
        except OSError:
            return artifacts

        for path in sorted(candidates):
            if not path.is_file() or path.suffix.lower() not in _ARTIFACT_EXTENSIONS:
                continue
            if stem and path.stem != stem:
                continue
            try:
                stat = path.stat()
            except OSError:
                size = 0
                mtime = 0.0
            else:
                size = stat.st_size
                mtime = stat.st_mtime
            if modified_since is not None and mtime < modified_since:
                continue
            artifacts.append({
                "path": str(path),
                "kind": path.suffix.lower().lstrip("."),
                "size": size,
                "modified_at": mtime,
            })
        return artifacts

    def _scan_diagnostics(
        self,
        work_dir: Path,
        stem: str | None = None,
        modified_since: float | None = None,
    ) -> list[dict]:
        """Extract high-signal warnings/errors from Abaqus text outputs."""
        diagnostics: list[dict] = []
        for artifact in self._collect_artifacts(work_dir, stem=stem, modified_since=modified_since):
            suffix = Path(artifact["path"]).suffix.lower()
            if suffix not in {".dat", ".msg", ".sta", ".log"}:
                continue
            path = Path(artifact["path"])
            try:
                fh = path.open("r", encoding="utf-8", errors="replace")
            except OSError:
                continue
            with fh:
                for lineno, line in enumerate(fh, start=1):
                    text = line.strip()
                    if not text:
                        continue
                    upper = text.upper()
                    level = None
                    if "ERROR" in upper or "ABORT" in upper or "TERMINATED" in upper:
                        level = "error"
                    elif "WARNING" in upper:
                        level = "warning"
                    if level is None:
                        continue
                    diagnostics.append({
                        "level": level,
                        "message": text[:500],
                        "source": str(path),
                        "line": lineno,
                    })
                    if len(diagnostics) >= 50:
                        return diagnostics
        return diagnostics

    # -- run_file -------------------------------------------------------------

    def run_file(self, script: Path) -> RunResult:
        """Execute an Abaqus script or input deck.

        - .inp: ``abaqus job=<stem> input=<file> interactive``
        - .py:  ``abaqus cae noGUI=<file>``
        """
        installs = self.detect_installed()
        if not installs:
            raise RuntimeError(_NOT_INSTALLED_HINT)

        abaqus_bat = installs[0].extra.get("bat", "abaqus")
        suffix = script.suffix.lower()
        work_dir = script.parent

        if suffix == ".inp":
            job_name = script.stem
            cmd = [abaqus_bat, f"job={job_name}", f"input={script.name}", "interactive"]
        elif suffix == ".py":
            cmd = [abaqus_bat, "cae", f"noGUI={script}"]
        else:
            cmd = [abaqus_bat, "cae", f"noGUI={script}"]

        start = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(work_dir),
                timeout=600,
            )
        except subprocess.TimeoutExpired:
            duration = time.monotonic() - start
            return RunResult(
                exit_code=-1,
                stdout="",
                stderr="Abaqus execution timed out after 600s",
                duration_s=round(duration, 3),
                script=str(script),
                solver=self.name,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        duration = time.monotonic() - start
        artifacts = self._collect_artifacts(work_dir, stem=script.stem)
        diagnostics = self._scan_diagnostics(work_dir, stem=script.stem)
        errors = [
            d["message"]
            for d in diagnostics
            if d.get("level") == "error"
        ]

        return RunResult(
            exit_code=proc.returncode,
            stdout=proc.stdout.strip() if proc.stdout else "",
            stderr=proc.stderr.strip() if proc.stderr else "",
            duration_s=round(duration, 3),
            script=str(script),
            solver=self.name,
            timestamp=datetime.now(timezone.utc).isoformat(),
            errors=errors,
            diagnostics=diagnostics,
            artifacts=artifacts,
        )

    # -- persistent CAE authoring session -------------------------------------

    def launch(
        self,
        mode: str = "cae",
        ui_mode: str = "no_gui",
        workspace: str | None = None,
        snippet_timeout: float | int | str | None = None,
        backend: str | None = None,
        launch_timeout: float | int | str | None = None,
        **kwargs,
    ) -> dict:
        """Create an Abaqus/CAE authoring session.

        By default this uses the conservative file-backed backend: every exec
        starts CAE, loads the session .cae file, runs the snippet, and saves it
        back. ``backend="bridge"`` starts one long-lived noGUI CAE process with
        a localhost command bridge for lower-latency iterative modeling.
        """
        installs = self.detect_installed()
        if not installs:
            raise RuntimeError(_NOT_INSTALLED_HINT)

        self._close_bridge()
        self._session_id = f"abaqus-{uuid.uuid4().hex[:8]}"
        self._session_mode = mode or "cae"
        self._session_ui_mode = ui_mode or "no_gui"
        self._session_backend = (backend or "file").replace("_", "-")
        if self._session_backend in {"file-backed-cae", "file-backed"}:
            self._session_backend = "file"
        if self._session_backend in {"live", "persistent"}:
            self._session_backend = "bridge"
        if self._session_backend not in {"file", "bridge"}:
            raise ValueError("Unsupported Abaqus session backend: %s" % self._session_backend)
        if self._session_backend == "bridge" and self._session_ui_mode not in {"no_gui", "nogui", "no-gui"}:
            raise ValueError("Abaqus bridge backend currently supports no_gui sessions only")
        self._abaqus_bat = installs[0].extra.get("bat", "abaqus")
        self._solver_version = installs[0].version
        if snippet_timeout is not None:
            self._snippet_timeout_s = float(snippet_timeout)
        else:
            self._snippet_timeout_s = 600.0
        if launch_timeout is not None:
            self._launch_timeout_s = float(launch_timeout)
        else:
            self._launch_timeout_s = 120.0
        root = Path(workspace) if workspace else Path.cwd() / ".sim" / "abaqus" / self._session_id
        root.mkdir(parents=True, exist_ok=True)
        self._session_workspace = root
        self._session_cae = root / "session.cae"
        self._run_count = 0
        self._last_result = None
        self._last_run_started_at = None

        if self._session_backend == "bridge":
            self._start_bridge()

        return {
            "ok": True,
            "session_id": self._session_id,
            "mode": self._session_mode,
            "ui_mode": self._session_ui_mode,
            "workspace": str(root),
            "cae_path": str(self._session_cae),
            "persistence": self._persistence(),
            "backend": self._session_backend,
            "snippet_timeout_s": self._snippet_timeout_s,
            "launch_timeout_s": self._launch_timeout_s,
            "health": self.health(),
            "bridge": {
                "host": self._bridge_host,
                "port": self._bridge_port,
                "pid": None if self._bridge_proc is None else self._bridge_proc.pid,
            } if self._session_backend == "bridge" else None,
        }

    def _require_session(self) -> tuple[Path, Path, str]:
        if self._session_workspace is None or self._session_cae is None or self._abaqus_bat is None:
            raise RuntimeError("No active Abaqus CAE session. Run sim connect first.")
        return self._session_workspace, self._session_cae, self._abaqus_bat

    def _write_bridge_server(self) -> Path:
        workspace, cae_path, _ = self._require_session()
        server_path = workspace / "sim_bridge_server.py"
        result = f'''# Auto-generated by sim-plugin-abaqus.
import contextlib
import io
import json
import os
import socket
import sys
import traceback

from abaqus import *
from abaqusConstants import *
from caeModules import *

HOST = "127.0.0.1"
PORT = int(os.environ.get("SIM_ABAQUS_BRIDGE_PORT", "0"))
READY_PATH = os.environ.get("SIM_ABAQUS_BRIDGE_READY")
TOKEN = os.environ["SIM_ABAQUS_BRIDGE_TOKEN"]
SESSION_CAE = {str(cae_path)!r}
CONNECTION_TIMEOUT_S = 10.0
MAX_REQUEST_BYTES = 10 * 1024 * 1024
_shutdown = False
_globals = globals()

def _repo_names(obj, attr):
    try:
        repo = getattr(obj, attr)
        return sorted([str(k) for k in repo.keys()])
    except Exception:
        return []

def _model_summary():
    out = {{"models": {{}}, "jobs": []}}
    try:
        out["jobs"] = sorted([str(k) for k in mdb.jobs.keys()])
    except Exception:
        pass
    try:
        items = mdb.models.items()
    except Exception:
        items = []
    for name, model in items:
        item = {{
            "parts": _repo_names(model, "parts"),
            "materials": _repo_names(model, "materials"),
            "sections": _repo_names(model, "sections"),
            "steps": _repo_names(model, "steps"),
            "loads": _repo_names(model, "loads"),
            "boundary_conditions": _repo_names(model, "boundaryConditions"),
        }}
        try:
            item["instances"] = sorted([str(k) for k in model.rootAssembly.instances.keys()])
        except Exception:
            item["instances"] = []
        out["models"][str(name)] = item
    return out

def _write_ready(port):
    payload = {{"ok": True, "host": HOST, "port": port, "session_cae": SESSION_CAE}}
    if READY_PATH:
        with open(READY_PATH, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, sort_keys=True)
    print("__SIM_BRIDGE_READY__" + json.dumps(payload, sort_keys=True))
    sys.stdout.flush()

def _save():
    mdb.saveAs(pathName=SESSION_CAE)

def _handle(req):
    global _shutdown
    if req.get("token") != TOKEN:
        return {{"ok": False, "error": "unauthorized"}}
    op = req.get("op")
    if op == "ping":
        return {{"ok": True, "pong": True}}
    if op == "inspect":
        return {{"ok": True, "model_summary": _model_summary()}}
    if op == "save":
        _save()
        return {{"ok": True, "cae_path": SESSION_CAE, "model_summary": _model_summary()}}
    if op == "shutdown":
        _shutdown = True
        return {{"ok": True, "shutdown": True}}
    if op == "exec":
        stdout = io.StringIO()
        stderr = io.StringIO()
        payload = {{"ok": True, "result": None, "model_summary": None}}
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exec(compile(req.get("code", ""), "<sim-bridge>", "exec"), _globals, _globals)
            payload["result"] = _globals.get("_sim_result")
            payload["model_summary"] = _model_summary()
            _save()
        except Exception as exc:
            payload["ok"] = False
            payload["error"] = str(exc)
            payload["traceback"] = traceback.format_exc()
            try:
                payload["model_summary"] = _model_summary()
            except Exception:
                pass
        payload["stdout"] = stdout.getvalue()
        payload["stderr"] = stderr.getvalue()
        return payload
    return {{"ok": False, "error": "unknown op: %s" % op}}

if os.path.exists(SESSION_CAE):
    openMdb(pathName=SESSION_CAE)

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind((HOST, PORT))
sock.listen(4)
sock.settimeout(0.25)
_write_ready(sock.getsockname()[1])

while not _shutdown:
    try:
        conn, _addr = sock.accept()
    except socket.timeout:
        continue
    try:
        with conn:
            conn.settimeout(CONNECTION_TIMEOUT_S)
            data = b""
            while not data.endswith(b"\\n"):
                chunk = conn.recv(65536)
                if not chunk:
                    break
                data += chunk
                if len(data) > MAX_REQUEST_BYTES:
                    raise ValueError("bridge request exceeds maximum size")
            try:
                req = json.loads(data.decode("utf-8"))
                resp = _handle(req)
            except Exception as exc:
                resp = {{"ok": False, "error": str(exc), "traceback": traceback.format_exc()}}
            conn.sendall((json.dumps(resp, default=str, sort_keys=True) + "\\n").encode("utf-8"))
    except Exception:
        continue
sock.close()
'''
        server_path.write_text(result, encoding="utf-8")
        return server_path

    def _start_bridge(self) -> None:
        workspace, _, abaqus_bat = self._require_session()
        server_path = self._write_bridge_server()
        ready_path = workspace / "bridge_ready.json"
        try:
            ready_path.unlink()
        except FileNotFoundError:
            pass
        self._bridge_stdout_path = workspace / "bridge.stdout.log"
        self._bridge_stderr_path = workspace / "bridge.stderr.log"
        self._bridge_token = secrets.token_hex(32)
        env = os.environ.copy()
        env["SIM_ABAQUS_BRIDGE_READY"] = str(ready_path)
        env["SIM_ABAQUS_BRIDGE_PORT"] = "0"
        env["SIM_ABAQUS_BRIDGE_TOKEN"] = self._bridge_token
        self._bridge_stdout_handle = self._bridge_stdout_path.open("w", encoding="utf-8", errors="replace")
        self._bridge_stderr_handle = self._bridge_stderr_path.open("w", encoding="utf-8", errors="replace")
        try:
            self._bridge_proc = subprocess.Popen(
                [abaqus_bat, "cae", f"noGUI={server_path}"],
                cwd=str(workspace),
                env=env,
                stdout=self._bridge_stdout_handle,
                stderr=self._bridge_stderr_handle,
                text=True,
            )
        except Exception:
            self._close_bridge(force=True)
            raise
        deadline = time.time() + self._launch_timeout_s
        while time.time() < deadline and not ready_path.exists():
            if self._bridge_proc.poll() is not None:
                message = self._bridge_failure_message("Abaqus bridge exited before it was ready")
                self._close_bridge(force=True)
                raise RuntimeError(message)
            time.sleep(0.25)
        if not ready_path.exists():
            self._close_bridge(force=True)
            raise TimeoutError("Timed out waiting for Abaqus bridge to become ready")
        ready = json.loads(ready_path.read_text(encoding="utf-8"))
        self._bridge_host = ready["host"]
        self._bridge_port = int(ready["port"])

    def _bridge_failure_message(self, prefix: str) -> str:
        pieces = [prefix]
        if self._bridge_stdout_path and self._bridge_stdout_path.exists():
            pieces.append("stdout_tail=" + self._bridge_stdout_path.read_text(encoding="utf-8", errors="replace")[-2000:])
        if self._bridge_stderr_path and self._bridge_stderr_path.exists():
            pieces.append("stderr_tail=" + self._bridge_stderr_path.read_text(encoding="utf-8", errors="replace")[-2000:])
        return "\n".join(pieces)

    def _bridge_request(self, payload: dict, timeout: float | None = None) -> dict:
        if self._bridge_proc is None or self._bridge_host is None or self._bridge_port is None or self._bridge_token is None:
            raise RuntimeError("Abaqus bridge is not connected")
        if self._bridge_proc.poll() is not None:
            raise RuntimeError(self._bridge_failure_message("Abaqus bridge process is not running"))
        request_timeout = timeout if timeout is not None else self._snippet_timeout_s
        request = dict(payload)
        request["token"] = self._bridge_token
        with socket.create_connection((self._bridge_host, self._bridge_port), timeout=request_timeout) as sock:
            sock.settimeout(request_timeout)
            sock.sendall((json.dumps(request) + "\n").encode("utf-8"))
            data = b""
            while not data.endswith(b"\n"):
                chunk = sock.recv(65536)
                if not chunk:
                    break
                data += chunk
        return json.loads(data.decode("utf-8"))

    def _close_bridge(self, force: bool = False) -> None:
        if self._bridge_proc is not None and self._bridge_proc.poll() is None:
            if force:
                self._bridge_proc.terminate()
            elif self._bridge_host is not None and self._bridge_port is not None:
                try:
                    self._bridge_request({"op": "shutdown"}, timeout=10)
                except Exception:
                    pass
            try:
                self._bridge_proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self._bridge_proc.terminate()
                try:
                    self._bridge_proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self._bridge_proc.kill()
        for handle in (self._bridge_stdout_handle, self._bridge_stderr_handle):
            if handle is not None:
                try:
                    handle.close()
                except Exception:
                    pass
        self._bridge_proc = None
        self._bridge_host = None
        self._bridge_port = None
        self._bridge_token = None
        self._bridge_stdout_handle = None
        self._bridge_stderr_handle = None

    def _write_cae_wrapper(self, code: str, label: str) -> tuple[Path, Path]:
        workspace, cae_path, _ = self._require_session()
        seq = self._run_count + 1
        snippet_path = workspace / f"snippet_{seq:04d}.py"
        wrapper_path = workspace / f"wrapper_{seq:04d}.py"
        result_path = workspace / f"result_{seq:04d}.json"
        snippet_path.write_text(code, encoding="utf-8")

        # The supported compatibility profiles use Abaqus Python with the
        # encoding= keyword available. Revisit if adding pre-2024 profiles.
        wrapper = f'''# Auto-generated by sim-plugin-abaqus.
from __future__ import print_function

import json
import os
import traceback

SESSION_CAE = {str(cae_path)!r}
SNIPPET_PATH = {str(snippet_path)!r}
RESULT_PATH = {str(result_path)!r}
LABEL = {label!r}

def _repo_names(obj, attr):
    try:
        repo = getattr(obj, attr)
        return sorted([str(k) for k in repo.keys()])
    except Exception:
        return []

def _model_summary():
    out = {{"models": {{}}, "jobs": []}}
    try:
        out["jobs"] = sorted([str(k) for k in mdb.jobs.keys()])
    except Exception:
        pass
    try:
        items = mdb.models.items()
    except Exception:
        items = []
    for name, model in items:
        item = {{
            "parts": _repo_names(model, "parts"),
            "materials": _repo_names(model, "materials"),
            "sections": _repo_names(model, "sections"),
            "steps": _repo_names(model, "steps"),
            "loads": _repo_names(model, "loads"),
            "boundary_conditions": _repo_names(model, "boundaryConditions"),
        }}
        try:
            item["instances"] = sorted([str(k) for k in model.rootAssembly.instances.keys()])
        except Exception:
            item["instances"] = []
        out["models"][str(name)] = item
    return out

payload = {{"ok": True, "label": LABEL, "result": None, "model_summary": None}}

try:
    from abaqus import *
    from abaqusConstants import *
    from caeModules import *

    if os.path.exists(SESSION_CAE):
        openMdb(pathName=SESSION_CAE)

    with open(SNIPPET_PATH, "r", encoding="utf-8") as fh:
        user_code = fh.read()
    exec(compile(user_code, SNIPPET_PATH, "exec"), globals(), globals())
    payload["result"] = globals().get("_sim_result")
    payload["model_summary"] = _model_summary()

    try:
        mdb.saveAs(pathName=SESSION_CAE)
    except Exception:
        try:
            mdb.save()
        except Exception:
            raise

except Exception as exc:
    payload["ok"] = False
    payload["error"] = str(exc)
    payload["traceback"] = traceback.format_exc()
    try:
        payload["model_summary"] = _model_summary()
    except Exception:
        pass

with open(RESULT_PATH, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, default=str, sort_keys=True)
print("__SIM_RESULT__" + json.dumps(payload, default=str, sort_keys=True))
'''
        wrapper_path.write_text(wrapper, encoding="utf-8")
        return wrapper_path, result_path

    def _run_cae_wrapper(self, wrapper_path: Path) -> subprocess.CompletedProcess[str]:
        _, _, abaqus_bat = self._require_session()
        if self._session_ui_mode in {"gui", "desktop", "visible"}:
            cmd = [abaqus_bat, "cae", f"script={wrapper_path}"]
        else:
            cmd = [abaqus_bat, "cae", f"noGUI={wrapper_path}"]
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(wrapper_path.parent),
            timeout=self._snippet_timeout_s,
        )

    def _payload_from_stdout_marker(self, stdout: str) -> dict:
        for line in reversed(stdout.splitlines()):
            line = line.strip()
            if not line.startswith("__SIM_RESULT__"):
                continue
            try:
                return json.loads(line[len("__SIM_RESULT__"):])
            except json.JSONDecodeError:
                return {}
        return {}

    def run(self, code: str, label: str = "") -> dict:
        """Execute Abaqus/CAE Python against the persistent .cae state."""
        try:
            workspace, cae_path, _ = self._require_session()
        except RuntimeError as exc:
            return {
                "ok": False,
                "error_code": "session_not_connected",
                "message": str(exc),
            }

        if self._session_backend == "bridge":
            return self._run_bridge(code, label)

        wrapper_path, result_path = self._write_cae_wrapper(code, label or "snippet")
        scan_since = time.time()
        self._last_run_started_at = scan_since
        start = time.monotonic()
        try:
            proc = self._run_cae_wrapper(wrapper_path)
        except subprocess.TimeoutExpired as exc:
            duration = time.monotonic() - start
            result = {
                "ok": False,
                "error_code": "timeout",
                "message": "Abaqus CAE snippet timed out after 600s",
                "stdout": exc.stdout or "",
                "stderr": exc.stderr or "",
                "duration_s": round(duration, 3),
            }
            self._last_result = result
            return result

        duration = time.monotonic() - start
        payload: dict = {}
        if result_path.is_file():
            try:
                payload = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {}
        if not payload:
            payload = self._payload_from_stdout_marker(proc.stdout or "")

        ok = proc.returncode == 0 and payload.get("ok", False) is True
        diagnostics = self._scan_diagnostics(workspace, modified_since=scan_since)
        artifacts = self._collect_artifacts(workspace, modified_since=scan_since)
        errors = [
            d["message"]
            for d in diagnostics
            if d.get("level") == "error"
        ]

        result = {
            "ok": ok and not errors,
            "label": label,
            "exit_code": proc.returncode,
            "stdout": proc.stdout.strip() if proc.stdout else "",
            "stderr": proc.stderr.strip() if proc.stderr else "",
            "duration_s": round(duration, 3),
            "workspace": str(workspace),
            "cae_path": str(cae_path),
            "result": payload.get("result"),
            "model_summary": payload.get("model_summary"),
            "diagnostics": diagnostics,
            "artifacts": artifacts,
            "errors": errors,
        }
        if not result["ok"]:
            result["message"] = (
                payload.get("error")
                or proc.stderr.strip()
                or "Abaqus CAE snippet failed without a result payload"
            )
            if payload.get("traceback"):
                result["traceback"] = payload["traceback"]

        self._run_count += 1
        self._last_result = result
        return result

    def _run_bridge(self, code: str, label: str = "") -> dict:
        workspace, cae_path, _ = self._require_session()
        scan_since = time.time()
        self._last_run_started_at = scan_since
        start = time.monotonic()
        try:
            payload = self._bridge_request(
                {"op": "exec", "code": code, "label": label or "snippet"},
                timeout=self._snippet_timeout_s,
            )
        except (OSError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
            duration = time.monotonic() - start
            diagnostics = self._scan_diagnostics(workspace, modified_since=scan_since)
            artifacts = self._collect_artifacts(workspace, modified_since=scan_since)
            result = {
                "ok": False,
                "label": label,
                "error_code": "bridge_request_failed",
                "exit_code": -1,
                "message": str(exc),
                "stdout": "",
                "stderr": "",
                "duration_s": round(duration, 3),
                "workspace": str(workspace),
                "cae_path": str(cae_path),
                "result": None,
                "model_summary": None,
                "diagnostics": diagnostics,
                "artifacts": artifacts,
                "errors": [d["message"] for d in diagnostics if d.get("level") == "error"],
                "backend": "bridge",
            }
            self._run_count += 1
            self._last_result = result
            return result

        duration = time.monotonic() - start
        diagnostics = self._scan_diagnostics(workspace, modified_since=scan_since)
        artifacts = self._collect_artifacts(workspace, modified_since=scan_since)
        errors = [
            d["message"]
            for d in diagnostics
            if d.get("level") == "error"
        ]
        ok = payload.get("ok", False) is True
        result = {
            "ok": ok and not errors,
            "label": label,
            "exit_code": 0 if ok else 1,
            "stdout": payload.get("stdout", ""),
            "stderr": payload.get("stderr", ""),
            "duration_s": round(duration, 3),
            "workspace": str(workspace),
            "cae_path": str(cae_path),
            "result": payload.get("result"),
            "model_summary": payload.get("model_summary"),
            "diagnostics": diagnostics,
            "artifacts": artifacts,
            "errors": errors,
            "backend": "bridge",
        }
        if not result["ok"]:
            result["message"] = payload.get("error") or "Abaqus bridge snippet failed"
            if payload.get("traceback"):
                result["traceback"] = payload["traceback"]
        self._run_count += 1
        self._last_result = result
        return result

    def query(self, name: str) -> dict:
        """Driver-specific inspect targets for Abaqus authoring sessions."""
        if name in {"session.summary", "health", "session.health"}:
            return self.health()
        if name in {"cae.model_summary", "model.summary"}:
            summary = (self._last_result or {}).get("model_summary")
            if summary is None and self._session_backend == "bridge":
                try:
                    response = self._bridge_request({"op": "inspect"}, timeout=30)
                    summary = response.get("model_summary")
                except Exception:
                    summary = None
            return {
                "connected": self._session_id is not None,
                "available": summary is not None,
                "model_summary": summary,
            }
        if name in {"workdir.files", "workspace.files"}:
            if self._session_workspace is None:
                return {"connected": False, "files": []}
            return {
                "connected": True,
                "workspace": str(self._session_workspace),
                "files": self._collect_artifacts(self._session_workspace),
            }
        if name in {"job.latest", "job.diagnostics"}:
            if self._session_workspace is None:
                return {"connected": False, "diagnostics": [], "artifacts": []}
            diagnostics = self._scan_diagnostics(
                self._session_workspace,
                modified_since=self._last_run_started_at,
            )
            return {
                "connected": True,
                "ok": None if self._last_result is None else self._last_result.get("ok"),
                "last_ok": None if self._last_result is None else self._last_result.get("ok"),
                "run_count": self._run_count,
                "diagnostics": diagnostics,
                "artifacts": self._collect_artifacts(self._session_workspace),
                "errors": [d["message"] for d in diagnostics if d.get("level") == "error"],
            }
        return {"ok": False, "error": f"unknown query: {name}"}

    def disconnect(self) -> dict:
        sid = self._session_id
        backend = self._session_backend
        self._close_bridge()
        self._session_id = None
        self._session_workspace = None
        self._session_cae = None
        self._session_backend = "file"
        self._abaqus_bat = None
        self._solver_version = None
        self._last_result = None
        self._last_run_started_at = None
        self._run_count = 0
        return {"ok": True, "session_id": sid, "backend": backend, "disconnected": True}
