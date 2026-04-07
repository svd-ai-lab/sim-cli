"""COMSOL Multiphysics driver for sim.

Phase 1: one-shot script execution via subprocess.
Phase 2: persistent GUI sessions via JPype + COMSOL Java API.

The JPype bridge loads COMSOL's bundled JRE and plugin jars, then calls
ModelUtil.initStandalone(true) for GUI or (false) for headless.
"""
from __future__ import annotations

import ast
import glob
import io
import json
import os
import re
import shutil
import time
import traceback
import uuid
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from sim.driver import ConnectionInfo, Diagnostic, LintResult

# Default COMSOL install path (Windows)
_DEFAULT_COMSOL_ROOT = r"C:\Program Files\COMSOL\COMSOL64\Multiphysics"


class ComsolDriver:
    @property
    def name(self) -> str:
        return "comsol"

    def detect(self, script: Path) -> bool:
        """Check if script imports mph (Python COMSOL interface)."""
        text = script.read_text()
        return bool(re.search(r"^\s*(import mph|from mph\b)", text, re.MULTILINE))

    def lint(self, script: Path) -> LintResult:
        """Validate a COMSOL/MPh script."""
        text = script.read_text()
        diagnostics: list[Diagnostic] = []

        has_import = bool(
            re.search(r"^\s*(import mph|from mph\b)", text, re.MULTILINE)
        )
        if not has_import:
            if "mph" in text:
                diagnostics.append(
                    Diagnostic(
                        level="error",
                        message="Script uses mph but does not import it",
                    )
                )
            else:
                diagnostics.append(
                    Diagnostic(level="error", message="No mph import found")
                )

        try:
            ast.parse(text)
        except SyntaxError as e:
            diagnostics.append(
                Diagnostic(level="error", message=f"Syntax error: {e}", line=e.lineno)
            )

        if has_import:
            try:
                tree = ast.parse(text)
                # Check for Client() call — needed to connect to COMSOL server
                has_client = any(
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "Client"
                    for node in ast.walk(tree)
                )
                # Also check for mph.start() which is the convenience launcher
                has_start = any(
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "start"
                    for node in ast.walk(tree)
                )
                if not has_client and not has_start:
                    diagnostics.append(
                        Diagnostic(
                            level="warning",
                            message="No mph.Client() or mph.start() call found "
                            "— script may not connect to COMSOL server",
                        )
                    )
            except SyntaxError:
                pass

        ok = not any(d.level == "error" for d in diagnostics)
        return LintResult(ok=ok, diagnostics=diagnostics)

    def connect(self) -> ConnectionInfo:
        """Check if mph is importable and COMSOL is available."""
        try:
            import mph

            version = mph.__version__
        except ImportError:
            return ConnectionInfo(
                solver="comsol",
                version=None,
                status="not_installed",
                message="mph is not installed in the current environment",
            )

        # Check if COMSOL executable is on PATH or discoverable by mph
        comsol_bin = shutil.which("comsol")
        if comsol_bin:
            return ConnectionInfo(
                solver="comsol",
                version=version,
                status="ok",
                message=f"mph {version} available, COMSOL found at {comsol_bin}",
            )

        # mph can still discover COMSOL via its own logic
        try:
            backends = mph.discovery.backend()
            if backends:
                return ConnectionInfo(
                    solver="comsol",
                    version=version,
                    status="ok",
                    message=f"mph {version} available, COMSOL discovered by mph",
                )
        except Exception:
            pass

        return ConnectionInfo(
            solver="comsol",
            version=version,
            status="not_installed",
            message=f"mph {version} installed but COMSOL not found on this machine",
        )

    def parse_output(self, stdout: str) -> dict:
        """Parse structured JSON output from a COMSOL/MPh script."""
        for line in reversed(stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        return {}

    # ── Phase 2: Persistent session via JPype ───────────────────────────────────

    def __init__(self):
        self._jvm_started = False
        self._model_util = None  # com.comsol.model.util.ModelUtil
        self._model = None       # active COMSOL model
        self._session_id: str | None = None
        self._ui_mode: str | None = None
        self._connected_at: float | None = None
        self._run_count: int = 0
        self._last_run: dict | None = None
        self._server_proc = None  # comsolmphserver subprocess
        self._client_proc = None  # comsolmphclient subprocess (GUI)
        self._port: int = 2036

    def _start_jvm(self, comsol_root: str | None = None) -> None:
        """Start JVM with COMSOL jars on the classpath."""
        if self._jvm_started:
            return

        import jpype
        import jpype.imports

        root = comsol_root or os.environ.get("COMSOL_ROOT", _DEFAULT_COMSOL_ROOT)
        jre_path = os.path.join(root, "java", "win64", "jre")
        plugins_dir = os.path.join(root, "plugins")
        lib_dir = os.path.join(root, "lib", "win64")

        jars = glob.glob(os.path.join(plugins_dir, "*.jar"))
        if not jars:
            raise RuntimeError(f"No COMSOL jars found in {plugins_dir}")

        classpath = os.pathsep.join(jars)
        jvm_dll = os.path.join(jre_path, "bin", "server", "jvm.dll")

        if not os.path.isfile(jvm_dll):
            raise RuntimeError(f"JVM not found at {jvm_dll}")

        jpype.startJVM(
            jvm_dll,
            f"-Djava.class.path={classpath}",
            f"-Dcs.root={root}",
            f"-Djava.library.path={lib_dir}",
            convertStrings=True,
        )
        self._jvm_started = True

    def _wait_for_port(self, port: int, timeout: float = 60) -> bool:
        """Wait until a TCP port is accepting connections."""
        import socket
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=2):
                    return True
            except OSError:
                time.sleep(2)
        return False

    def launch(self, ui_mode: str = "gui", comsol_root: str | None = None,
               user: str | None = None, password: str | None = None) -> dict:
        """Launch COMSOL server + optional GUI client, connect via JPype.

        1. Starts comsolmphserver.exe (headless compute backend)
        2. Waits for it to listen on the port
        3. Connects via ModelUtil.connect() from JPype
        4. If ui_mode='gui', also launches comsolmphclient.exe (visual GUI)
        """
        import subprocess

        root = comsol_root or os.environ.get("COMSOL_ROOT", _DEFAULT_COMSOL_ROOT)
        user = user or os.environ.get("COMSOL_USER", "")
        password = password or os.environ.get("COMSOL_PASSWORD", "")
        bin_dir = os.path.join(root, "bin", "win64")
        server_exe = os.path.join(bin_dir, "comsolmphserver.exe")
        client_exe = os.path.join(bin_dir, "comsolmphclient.exe")

        if not os.path.isfile(server_exe):
            raise RuntimeError(f"comsolmphserver not found at {server_exe}")

        # Step 1: Launch COMSOL server
        # -multi on: keep models in memory, allow multiple clients
        # -login auto: use stored credentials, don't prompt
        # -silent: don't listen to stdin
        # -graphics: enable graphics (needed for plot/image export)
        # -3drend sw: software rendering (no GPU needed)
        self._server_proc = subprocess.Popen(
            [server_exe, "-port", str(self._port), "-multi", "on",
             "-login", "auto", "-silent", "-graphics", "-3drend", "sw"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Step 2: Wait for server to start listening
        if not self._wait_for_port(self._port, timeout=90):
            self._server_proc.kill()
            self._server_proc = None
            raise RuntimeError(
                f"comsolmphserver did not start listening on port {self._port} "
                "within 90s — check COMSOL license"
            )

        # Step 3: Connect via JPype
        self._start_jvm(root)
        from com.comsol.model.util import ModelUtil  # type: ignore

        if user and password:
            ModelUtil.connect("localhost", self._port, user, password)
        else:
            ModelUtil.connect("localhost", self._port)

        # Handle concurrent access: wait up to 30s if server is busy
        from com.comsol.model.util import ServerBusyHandler  # type: ignore
        ModelUtil.setServerBusyHandler(ServerBusyHandler(30000))
        self._model_util = ModelUtil
        self._model = ModelUtil.create("Model1")

        # Step 4: Launch GUI client if requested
        if ui_mode in ("gui", "desktop") and os.path.isfile(client_exe):
            self._client_proc = subprocess.Popen(
                [client_exe, "-port", str(self._port)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        self._session_id = str(uuid.uuid4())
        self._ui_mode = ui_mode
        self._connected_at = time.time()
        self._run_count = 0
        self._last_run = None

        return {
            "ok": True,
            "session_id": self._session_id,
            "mode": "client-server",
            "source": "launch",
            "ui_mode": ui_mode,
            "port": self._port,
            "model_tag": str(self._model.tag()),
        }

    def run(self, code: str, label: str = "comsol-snippet") -> dict:
        """Execute a Python snippet with `model` and `ModelUtil` in scope."""
        if self._model is None:
            raise RuntimeError("No active COMSOL session — call launch() first")

        namespace: dict = {
            "model": self._model,
            "ModelUtil": self._model_util,
            "_result": None,
        }

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        error: str | None = None
        ok = True
        started_at = time.time()

        try:
            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                exec(code, namespace)  # noqa: S102
        except Exception:
            ok = False
            error = traceback.format_exc()

        elapsed = round(time.time() - started_at, 4)
        self._run_count += 1

        # Update model reference in case snippet loaded a new model
        if namespace.get("model") is not self._model and namespace.get("model") is not None:
            self._model = namespace["model"]

        record = {
            "run_id": str(uuid.uuid4()),
            "ok": ok,
            "label": label,
            "stdout": stdout_buf.getvalue(),
            "stderr": stderr_buf.getvalue(),
            "error": error,
            "result": namespace.get("_result"),
            "elapsed_s": elapsed,
        }
        self._last_run = record
        return record

    def disconnect(self) -> None:
        """Disconnect from COMSOL server and kill subprocesses."""
        if self._model_util is not None:
            try:
                self._model_util.disconnect()
            except Exception:
                pass
        if self._client_proc is not None:
            try:
                self._client_proc.kill()
            except Exception:
                pass
            self._client_proc = None
        if self._server_proc is not None:
            try:
                self._server_proc.kill()
            except Exception:
                pass
            self._server_proc = None
        self._model = None
        self._model_util = None
        self._session_id = None
        self._connected_at = None
        self._run_count = 0
        self._last_run = None
