"""ANSA pre-processor driver for sim.

Phase 1: one-shot batch execution via ansa64.bat -execscript -nogui.

BETA CAE ANSA is a CAE pre-processor for geometry cleanup, mesh generation,
and solver deck setup.  Its scripting interface is Python (the ``ansa`` module,
available only inside the ANSA process).  Project format is ``.ansa`` (binary
database) and scripts are standard ``.py`` files that ``import ansa``.

Batch execution::

    ansa64.bat -execscript "script.py|main()" -nogui
"""
from __future__ import annotations

import ast
import glob
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from sim.driver import ConnectionInfo, Diagnostic, LintResult, RunResult, SolverInstall

# Pattern to detect ANSA Python scripts
_ANSA_IMPORT_RE = re.compile(
    r"^\s*(import\s+ansa|from\s+ansa[\s.])", re.MULTILINE
)

# GUI-only functions that won't work in -nogui batch mode
_GUI_ONLY_PATTERNS = (
    "PickEntities",
    "guitk.",
    "ansa.guitk",
    "UserInput",
)

# Drives to scan when searching for ANSA on Windows
_SCAN_DRIVES = ("C", "D", "E", "F", "G")


# ANSA stdout often surfaces Python exceptions thrown inside main() via the
# IAP protocol. Most are caught by PythonTracebackProbe, but ANSA's own
# scripting errors (e.g. base.* failures) print "ANSA error:" lines.
_ANSA_STDOUT_RULES: list[dict] = [
    {"pattern": r"ANSA error:", "severity": "error",
     "code": "ansa.scripting.error"},
    {"pattern": r"License checkout failed", "severity": "error",
     "code": "ansa.license.checkout_failed"},
]


def _default_ansa_probes(enable_gui: bool = False) -> list:
    """ANSA probe list — generic_probes() + ANSA-specific channels.

    Generic (via generic_probes()):
      #1  ProcessMetaProbe      #1+ RuntimeTimeoutProbe
      #3  StdoutJsonTailProbe   #3+ PythonTracebackProbe   #9 WorkdirDiffProbe

    ANSA-specific:
      #6  TextStreamRulesProbe(ansa:stdout) — ANSA error / license patterns
      #5  DomainExceptionMapProbe — post-processor
      #8a GuiDialogProbe — only when enable_gui (ANSA -listenport, no -nogui)
      #8b ScreenshotProbe — only when enable_gui

    NOT wired:
      #2  stderr — ANSA's IAP funnels everything through stdout
      #4  SdkAttributeProbe — IAP exec_snippet returns dict already
      #7  log file — no per-session log
    """
    from sim.inspect import (                                            # noqa: PLC0415
        DomainExceptionMapProbe, GuiDialogProbe, ScreenshotProbe,
        TextStreamRulesProbe, generic_probes,
    )
    _g = {p.name: p for p in generic_probes()}
    probes: list = [
        _g["process-meta"],                                              # #1
        _g["runtime-timeout"],                                           # #1+
        TextStreamRulesProbe(                                            # #6
            source="ansa:stdout",
            text_selector=lambda ctx: ctx.stdout,
            rules=_ANSA_STDOUT_RULES,
        ),
        _g["stdout-json-tail"],                                          # #3
        _g["python-traceback"],                                          # #3+
        DomainExceptionMapProbe(),                                        # #5
    ]
    if enable_gui:
        probes.append(GuiDialogProbe(                                    # #8a
            process_name_substrings=("ansa", "ansa64"),
            code_prefix="ansa.gui"))
        probes.append(ScreenshotProbe(                                   # #8b
            filename_prefix="ansa_shot",
            process_name_substrings=("ansa", "ansa64")))
    probes.append(_g["workdir-diff"])                                    # #9
    return probes


def _find_installation() -> tuple[str, str, str] | None:
    """Locate BETA CAE ANSA installation.

    Returns (bat_path, exe_path, version) or None.

    Search order:
    1. ANSA_EXEC_DIR or ANSA_HOME environment variable
    2. System PATH (shutil.which "ansa64.bat")
    3. Common install dirs on all lettered drives (glob)
    """
    # 1. Environment variables
    for env_var in ("ANSA_EXEC_DIR", "ANSA_EXEC_PATH"):
        env_val = os.environ.get(env_var, "").strip()
        if env_val:
            bat = os.path.join(env_val, "ansa64.bat")
            if os.path.isfile(bat):
                version = _extract_version(env_val)
                exe = _find_exe_from_bat_dir(env_val)
                return bat, exe or "", version or "unknown"

    # 2. PATH
    bat_on_path = shutil.which("ansa64.bat")
    if bat_on_path:
        bat_dir = str(Path(bat_on_path).parent)
        version = _extract_version(bat_dir)
        exe = _find_exe_from_bat_dir(bat_dir)
        return bat_on_path, exe or "", version or "unknown"

    # 3. Glob common install dirs
    for drive in _SCAN_DRIVES:
        for prog_dir in (
            fr"{drive}:\Program Files (x86)\ANSA",
            fr"{drive}:\Program Files\ANSA",
            fr"{drive}:\BETA",
            fr"{drive}:\ANSA",
        ):
            pattern = os.path.join(prog_dir, "ansa_v*", "ansa64.bat")
            matches = sorted(glob.glob(pattern), reverse=True)  # newest first
            if matches:
                bat = matches[0]
                bat_dir = str(Path(bat).parent)
                version = _extract_version(bat_dir)
                exe = _find_exe_from_bat_dir(bat_dir)
                return bat, exe or "", version or "unknown"

    return None


def _extract_version(path: str) -> str | None:
    """Extract version from path (e.g., 'ansa_v25.0.0' -> '25.0.0')."""
    m = re.search(r"ansa_v(\d+\.\d+\.\d+)", path, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"v(\d+\.\d+\.\d+)", path)
    if m:
        return m.group(1)
    return None


def _find_exe_from_bat_dir(bat_dir: str) -> str | None:
    """Find ansa_win64.exe from the ansa64.bat directory."""
    # ansa64.bat is in ansa_vX.X.X/, exe is in ../shared_vX.X.X/win64/
    parent = str(Path(bat_dir).parent)
    for d in sorted(glob.glob(os.path.join(parent, "shared_v*", "win64", "ansa_win64.exe")), reverse=True):
        return d
    return None


class AnsaDriver:
    """Sim driver for BETA CAE ANSA.

    Supports two execution models:

    Phase 1 — One-shot batch:
        run_file(script) → RunResult
        Launches ansa_win64.exe -execscript, captures output, exits.

    Phase 2 — Persistent session via IAP (Inter-ANSA Protocol):
        launch()    → start ANSA with -listenport, connect via IAP
        run(code)   → execute snippet in live session, return result dict
        disconnect() → goodbye + cleanup
    """

    def __init__(self):
        self._runtime = None  # lazy AnsaRuntime, created on first launch()
        self.probes: list = _default_ansa_probes(enable_gui=False)
        self._sim_dir = Path.cwd() / ".sim"

    @property
    def name(self) -> str:
        return "ansa"

    @property
    def supports_session(self) -> bool:
        return True

    # -- DriverProtocol -------------------------------------------------------

    def detect(self, script: Path) -> bool:
        """Return True for ANSA files.

        Accepts:
        - .py files containing ``import ansa`` or ``from ansa import``
        - .ansa files (native ANSA database)
        """
        ext = script.suffix.lower()

        if ext == ".ansa":
            return True

        if ext == ".py":
            try:
                header = script.read_bytes()[:4096].decode("utf-8", errors="replace")
                return bool(_ANSA_IMPORT_RE.search(header))
            except OSError:
                return False

        return False

    def lint(self, script: Path) -> LintResult:
        """Validate an ANSA script or database file.

        For .py scripts:
          - Validates Python syntax (ast.parse)
          - Checks for ``import ansa`` / ``from ansa import``
          - Warns if no ``main()`` function (convention for -execscript)
          - Warns if GUI-only functions used (won't work with -nogui)

        For .ansa files:
          - Checks file exists and is non-empty

        Works without ANSA installed.
        """
        ext = script.suffix.lower()
        if ext == ".py":
            return self._lint_python(script)
        if ext == ".ansa":
            return self._lint_ansa_db(script)
        return LintResult(
            ok=False,
            diagnostics=[Diagnostic(
                level="error",
                message=f"Unsupported file type '{script.suffix}'. "
                        "Expected .py (ANSA script) or .ansa (database).",
            )],
        )

    def _lint_python(self, script: Path) -> LintResult:
        diagnostics: list[Diagnostic] = []
        try:
            text = script.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return LintResult(ok=False, diagnostics=[
                Diagnostic(level="error", message=f"Cannot read file: {e}")
            ])

        if not text.strip():
            return LintResult(ok=False, diagnostics=[
                Diagnostic(level="error", message="Script is empty")
            ])

        # Syntax check
        try:
            tree = ast.parse(text)
        except SyntaxError as e:
            return LintResult(ok=False, diagnostics=[
                Diagnostic(level="error", message=f"Syntax error: {e}", line=e.lineno)
            ])

        # Import check
        has_ansa_import = bool(_ANSA_IMPORT_RE.search(text))
        if not has_ansa_import:
            diagnostics.append(Diagnostic(
                level="error",
                message="No 'import ansa' or 'from ansa import' found. "
                        "This does not appear to be an ANSA script.",
            ))
            return LintResult(ok=False, diagnostics=diagnostics)

        # Check for main() function (convention for -execscript entry point)
        has_main = any(
            isinstance(node, ast.FunctionDef) and node.name == "main"
            for node in ast.walk(tree)
        )
        if not has_main:
            diagnostics.append(Diagnostic(
                level="warning",
                message="No main() function defined. "
                        "The -execscript flag requires a callable entry point "
                        "(e.g., 'script.py|main()').",
            ))

        # Check for GUI-only functions (won't work with -nogui)
        for pattern in _GUI_ONLY_PATTERNS:
            if pattern in text:
                diagnostics.append(Diagnostic(
                    level="warning",
                    message=f"Script uses '{pattern}' which requires GUI. "
                            "This will fail in batch mode (-nogui).",
                ))
                break  # one warning is enough

        return LintResult(ok=True, diagnostics=diagnostics)

    def _lint_ansa_db(self, script: Path) -> LintResult:
        diagnostics: list[Diagnostic] = []
        try:
            size = script.stat().st_size
        except OSError as e:
            return LintResult(ok=False, diagnostics=[
                Diagnostic(level="error", message=f"Cannot access file: {e}")
            ])

        if size == 0:
            return LintResult(ok=False, diagnostics=[
                Diagnostic(level="error", message="ANSA database file is empty")
            ])

        return LintResult(ok=True, diagnostics=diagnostics)

    def connect(self) -> ConnectionInfo:
        """Check if BETA CAE ANSA is available on this machine.

        Does not launch ANSA. Reports install path and version when found.
        """
        result = _find_installation()
        if result is None:
            return ConnectionInfo(
                solver="ansa",
                version=None,
                status="not_installed",
                message=(
                    "BETA CAE ANSA not found. "
                    "Ensure ansa64.bat is on PATH or set ANSA_EXEC_DIR."
                ),
            )
        bat_path, exe_path, version = result
        return ConnectionInfo(
            solver="ansa",
            version=version,
            status="ok",
            message=f"ANSA {version} found at {bat_path}",
            solver_version=version,
        )

    def detect_installed(self) -> list[SolverInstall]:
        """Enumerate BETA CAE ANSA installations on this host.

        Thin wrapper around the existing _find_installation() helper which
        already walks ANSA_EXEC_DIR / ANSA_EXEC_PATH → PATH → glob of
        common install dirs across drives. Returns at most one entry —
        ANSA has a single canonical bat_path per host.

        Pure stdlib. Returns [] when nothing is found.
        """
        result = _find_installation()
        if result is None:
            return []
        bat_path, exe_path, version = result
        # Normalize "25.0.0" → "25.0" for the resolver short form
        short = ".".join(version.split(".")[:2]) if version != "unknown" else "unknown"
        return [
            SolverInstall(
                name="ansa",
                version=short,
                path=str(Path(bat_path).parent),
                source="_find_installation",
                extra={
                    "raw_version": version,
                    "bat_path": bat_path,
                    "exe_path": exe_path,
                    "release_label": f"ansa_v{version}" if version != "unknown" else "ansa_v?",
                },
            )
        ]

    def parse_output(self, stdout: str) -> dict:
        """Extract structured results from ANSA stdout.

        Convention: scripts print a JSON object as the last line:
            print(json.dumps({"element_count": 12345, "min_quality": 0.32}))

        Scans stdout in reverse and returns the first line that parses as JSON.
        Returns {} if no JSON found.
        """
        for line in reversed(stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        return {}

    def run_file(self, script: Path) -> RunResult:
        """Execute an ANSA script in batch mode.

        For .py scripts:
            Runs via ansa64.bat -execscript "script.py|main()" -nogui.
            If no main() exists, falls back to -exec "load_script: 'script.py'" -nogui.

        For .ansa files:
            Not directly executable. Raises RuntimeError with guidance.

        Raises RuntimeError if ANSA is not installed.
        """
        installation = _find_installation()
        if installation is None:
            raise RuntimeError(
                "BETA CAE ANSA not found. "
                "Install ANSA or ensure ansa64.bat is on PATH."
            )
        bat_path, exe_path, version = installation

        ext = script.suffix.lower()
        if ext == ".py":
            return self._run_python(script, bat_path)

        if ext == ".ansa":
            raise RuntimeError(
                f"Cannot directly execute .ansa database file '{script.name}'. "
                "Write a .py script that opens the .ansa file: "
                "base.Open('model.ansa') and performs the desired operations."
            )

        raise RuntimeError(
            f"Unsupported file type '{script.suffix}'. "
            "Expected .py (ANSA script) or .ansa (database)."
        )

    def _run_python(self, script: Path, bat_path: str) -> RunResult:
        """Execute a Python script inside ANSA batch mode.

        Builds a wrapper .bat that sets environment variables and calls
        ansa_win64.exe directly, avoiding ansa64.bat path-quoting issues
        when the install directory contains spaces.
        """
        import tempfile

        script_abs = str(script.resolve())

        # Check if script has main() to decide invocation method
        try:
            text = script.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(text)
            has_main = any(
                isinstance(node, ast.FunctionDef) and node.name == "main"
                for node in ast.walk(tree)
            )
        except Exception:
            has_main = False

        # Build the ANSA command argument
        if has_main:
            ansa_arg = f'-execscript "{script_abs}|main()"'
        else:
            ansa_arg = f"-exec \"load_script: '{script_abs}'\""

        # Derive paths from bat_path (ansa64.bat is in ansa_vX.X.X/)
        bat_dir = str(Path(bat_path).parent)  # ansa_vX.X.X/
        parent_dir = str(Path(bat_dir).parent)  # ANSA install root
        version = _extract_version(bat_dir) or "25.0.0"
        shared_dir = os.path.join(parent_dir, f"shared_v{version}")
        exe_path = os.path.join(shared_dir, "win64", "ansa_win64.exe")

        # Fall back to ansa64.bat if exe not found
        if not os.path.isfile(exe_path):
            exe_path = None

        # Write wrapper .bat that sets env and calls exe directly
        tmp_dir = tempfile.mkdtemp(prefix="sim_ansa_")
        wrapper = os.path.join(tmp_dir, "_sim_run.bat")
        with open(wrapper, "w", encoding="ascii") as f:
            f.write("@echo off\r\n")
            if exe_path:
                # Direct exe invocation — avoids ansa64.bat path issues
                f.write(f'if not defined ANSA_SRV set ANSA_SRV=localhost\r\n')
                f.write(f'set "ANSA_EXEC_DIR={bat_dir}\\"\r\n')
                f.write(f'set "ANSA_EXEC_PATH={bat_dir}\\"\r\n')
                f.write(f'set "BETA_SHARED_DIR={shared_dir}\\"\r\n')
                f.write(f'set "QTDIR={shared_dir}\\win64"\r\n')
                f.write(f'set "QT_PLUGIN_PATH=%QTDIR%\\plugins"\r\n')
                f.write(f'set QTWEBENGINE_DISABLE_SANDBOX=1\r\n')
                f.write(f'set "PYTHONHOME={shared_dir}\\python\\win64\\"\r\n')
                f.write(f'set "ANSA_HOME={bat_dir}\\config\\"\r\n')
                f.write(f'set HDF5_DISABLE_VERSION_CHECK=2\r\n')
                f.write(f'"{exe_path}" {ansa_arg} -nogui\r\n')
            else:
                # Fallback: call ansa64.bat
                f.write(f'if not defined ANSA_SRV set ANSA_SRV=localhost\r\n')
                f.write(f'call "{bat_path}" {ansa_arg} -nogui\r\n')

        start = time.monotonic()
        proc = subprocess.run(
            ["cmd", "/c", wrapper],
            capture_output=True,
            text=True,
            cwd=str(script.parent),
            timeout=600,  # 10 minute timeout for large models
        )
        duration = time.monotonic() - start

        # Cleanup temp dir
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass

        return RunResult(
            exit_code=proc.returncode,
            stdout=proc.stdout.strip(),
            stderr=proc.stderr.strip(),
            duration_s=round(duration, 3),
            script=str(script),
            solver=self.name,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    # -- Phase 2: IAP persistent session --------------------------------------

    def _ensure_runtime(self):
        if self._runtime is None:
            from sim.drivers.ansa.runtime import AnsaRuntime
            self._runtime = AnsaRuntime()
        return self._runtime

    def launch(self, port: int | None = None, ui_mode: str = "gui", **kwargs) -> dict:
        """Start ANSA in listener mode and establish IAP connection.

        Args:
            port: TCP port for IAP. Auto-assigned if None.
            ui_mode: "no_gui" (headless) or "gui" (visible ANSA window).

        Returns a session info dict with session_id, port, etc.
        """
        rt = self._ensure_runtime()
        info = rt.launch(port=port, ui_mode=ui_mode)
        self.probes = _default_ansa_probes(enable_gui=(ui_mode == "gui"))
        return info.to_dict()

    def _dispatch(self, code: str, label: str = "ansa-snippet") -> dict:
        """Execute a snippet inside the ANSA session (no probes attached)."""
        rt = self._ensure_runtime()
        record = rt.exec_snippet(code, label=label)
        return record.to_run_result()

    def run(self, code: str, label: str = "ansa-snippet") -> dict:
        """Execute a Python snippet inside the live ANSA session.

        The snippet runs with full access to the ``ansa`` module
        (base, constants, mesh, etc.). If main() is defined and returns
        a dict with string keys/values, it is captured as the result.
        """
        from sim.inspect import InspectCtx, collect_diagnostics         # noqa: PLC0415

        wd = self._sim_dir
        try:
            wd.mkdir(parents=True, exist_ok=True)
            before = sorted(
                str(p.relative_to(wd)).replace("\\", "/")
                for p in wd.rglob("*") if p.is_file()
            )
        except Exception:
            before = []

        t0 = time.monotonic()
        result = self._dispatch(code, label)
        wall = time.monotonic() - t0

        ctx = InspectCtx(
            stdout=result.get("stdout", "") or "",
            stderr=result.get("stderr", "") or result.get("error", "") or "",
            workdir=str(wd),
            wall_time_s=wall,
            exit_code=0 if result.get("ok") else 1,
            driver_name=self.name,
            session_ns={"_result": result.get("result")},
            workdir_before=before,
        )
        diags, arts = collect_diagnostics(self.probes, ctx)
        result["diagnostics"] = [d.to_dict() for d in diags]
        result["artifacts"] = [a.to_dict() for a in arts]
        return result

    def run_script(self, filepath: str, label: str | None = None) -> dict:
        """Execute a script file inside the live ANSA session via IAP."""
        rt = self._ensure_runtime()
        record = rt.exec_file(filepath, label=label)
        return record.to_run_result()

    def disconnect(self, keep_listening: bool = False) -> dict:
        """Terminate the IAP connection and optionally shut down ANSA."""
        if self._runtime is not None:
            self._runtime.disconnect(keep_listening=keep_listening)
        return {"ok": True, "disconnected": True}

    @property
    def is_connected(self) -> bool:
        """True if an IAP session is active."""
        return self._runtime is not None and self._runtime.is_connected
