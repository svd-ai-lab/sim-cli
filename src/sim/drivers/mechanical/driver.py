"""Ansys Mechanical driver for sim.

SDK-first design: uses ``ansys-mechanical-core`` (PyMechanical) to launch
Mechanical with a **visible GUI window**, then drives it via
``run_python_script``. The visible GUI is mandatory — sim's observation
commands (``sim screenshot``, etc.) depend on Mechanical's window being
on the desktop so :class:`PIL.ImageGrab` can capture it.

First principles:
    • PyWorkbench orchestrates Workbench cells (Engineering Data, Geometry,
      Model). See sim.drivers.workbench.
    • PyMechanical drives Mechanical (BCs, solve, results). Cells 4-6 of
      the Static Structural workflow belong to this driver.
    • Observation coupling: sim runs a PyMechanical gRPC client in-process
      while Mechanical's GUI window lives on the same desktop. Every ``exec``
      is a ``run_python_script`` call that mutates Mechanical's in-memory
      model **and** the GUI redraws — so a follow-up ``screenshot`` sees
      the effect.

Execution model:
    1. ``launch`` — start ``AnsysWBU.exe -DSApplet`` via
       ``pm.launch_mechanical(batch=False)``. Returns a gRPC client.
    2. ``run(code, label)`` — send the snippet to
       ``client.run_python_script(code)``. Snippets run inside Mechanical's
       IronPython interpreter, where ``ExtAPI``, ``DataModel``, ``Model`` are
       all available globals.
    3. ``query(name)`` — session metadata (no round-trip) for
       ``session.summary``. Project/file queries round-trip via the SDK.
    4. ``disconnect`` — ``client.exit()``.

Detection is done via :func:`ansys.tools.path.find_mechanical`, which scans
``AWP_ROOTxxx`` env vars and standard install layouts for ``AnsysWBU.exe``.
We fall back to manual directory probing when that helper is unavailable.
"""
from __future__ import annotations

import ast
import json
import logging
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from sim.driver import (
    ConnectionInfo,
    Diagnostic,
    LintResult,
    RunResult,
    SolverInstall,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# IronPython error patterns on stdout (run_python_script return value).
# Mechanical doesn't produce stderr through the gRPC interface.
_MECH_STDOUT_RULES: list[dict] = [
    {"pattern": r"\bError\b", "severity": "error", "code": "mech.scripting.error"},
    {"pattern": r"\bWarning\b", "severity": "warning", "code": "mech.scripting.warning"},
    # Ansys license errors surface in the run_python_script return string
    {"pattern": r"Cannot checkout", "severity": "error", "code": "mech.license.checkout_failed"},
]

# IronPython identifiers that indicate a Mechanical scripting snippet.
_MECH_SCRIPT_MARKERS = (
    "ExtAPI.",
    "DataModel.Project",
    "Model.Analyses",
    "Model.Geometry",
    "Model.Mesh",
    "Model.Materials",
    "ExtAPI.DataModel",
)

_MECH_PY_IMPORT = re.compile(
    r"^\s*(import\s+ansys\.mechanical|from\s+ansys\.mechanical\b)",
    re.MULTILINE,
)

_AWP_ROOT_RE = re.compile(r"^AWP_ROOT(\d{3})$")
_VERSION_DIR_RE = re.compile(r"v(\d{2})(\d)$")


def _default_mechanical_probes(enable_gui: bool = True) -> list:
    """Mechanical probe list — generic_probes() + Mechanical-specific channels.

    Generic (via generic_probes()):
      #1  ProcessMetaProbe      #1+ RuntimeTimeoutProbe
      #3  StdoutJsonTailProbe   #3+ PythonTracebackProbe   #9 WorkdirDiffProbe

    Mechanical-specific:
      #6  TextStreamRulesProbe(mech:stdout) — Error/Warning in script return value
      #5  DomainExceptionMapProbe           — post-processor
      #8a GuiDialogProbe                    — Mechanical GUI / Script Error dialog
      #8b ScreenshotProbe                   — GUI screenshot

    NOT wired:
      #2  stderr — always "" (run_python_script doesn't produce stderr)
      #4  SdkAttributeProbe — get_product_info() is expensive, skip
      #7  log — no per-session log accessible via gRPC

    enable_gui=True by default because Mechanical always launches with a
    visible GUI window (batch=False is the driver's policy).
    """
    from sim.inspect import (                                          # noqa: PLC0415
        DomainExceptionMapProbe, GuiDialogProbe, ScreenshotProbe,
        TextStreamRulesProbe, generic_probes,
    )
    _g = {p.name: p for p in generic_probes()}
    probes: list = [
        _g["process-meta"],                                            # #1  通用
        _g["runtime-timeout"],                                         # #1+ 通用
        TextStreamRulesProbe(                                          # #6  via stdout
            source="mech:stdout",
            text_selector=lambda ctx: ctx.stdout,
            rules=_MECH_STDOUT_RULES,
        ),
        _g["stdout-json-tail"],                                        # #3  通用
        _g["python-traceback"],                                        # #3+ 通用
        DomainExceptionMapProbe(),                                      # #5  post-processor
    ]
    if enable_gui:
        probes.append(GuiDialogProbe(                                  # #8a
            process_name_substrings=("AnsysWBU", "Mechanical", "ANSYS"),
            code_prefix="mech.gui"))
        probes.append(ScreenshotProbe(                                 # #8b
            filename_prefix="mech_shot",
            process_name_substrings=("AnsysWBU", "Mechanical", "ANSYS")))
    probes.append(_g["workdir-diff"])                                  # #9  通用（始终最后）
    return probes


def _version_code(version_str: str) -> int:
    """'24.1' → 241 (PyMechanical expects int)."""
    return int(version_str.replace(".", ""))


def _try_import_pymechanical():
    """Return the ``ansys.mechanical.core`` module or None."""
    try:
        import ansys.mechanical.core as pm  # noqa: F811
        return pm
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

class MechanicalDriver:
    """Driver for Ansys Mechanical — SDK-only (PyMechanical)."""

    def __init__(self):
        self._client: Any = None          # PyMechanical Mechanical client
        self._session_id: str | None = None
        self._mode: str | None = None
        self._ui_mode: str | None = None
        self._run_count: int = 0
        self._version: str | None = None
        self._launched_at: float | None = None
        self._sim_dir: Path = Path(os.environ.get("SIM_DIR") or (Path.cwd() / ".sim"))
        self.probes: list = _default_mechanical_probes(enable_gui=True)

    # ── DriverProtocol ─────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "mechanical"

    def detect(self, script: Path) -> bool:
        if not script.exists():
            return False
        ext = script.suffix.lower()
        try:
            text = script.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return False
        if ext == ".py":
            if _MECH_PY_IMPORT.search(text):
                return True
            # Also accept "Mechanical IronPython" scripts that use ExtAPI
            return any(m in text for m in _MECH_SCRIPT_MARKERS)
        if ext == ".mecdat":
            return True
        return False

    def lint(self, script: Path) -> LintResult:
        diagnostics: list[Diagnostic] = []

        try:
            text = script.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic("error", f"cannot read file: {e}")],
            )

        try:
            ast.parse(text)
        except SyntaxError as e:
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic("error", f"syntax error: {e}", e.lineno)],
            )

        has_sdk_import = bool(_MECH_PY_IMPORT.search(text))
        has_ext_api = any(m in text for m in _MECH_SCRIPT_MARKERS)

        if not has_sdk_import and not has_ext_api:
            diagnostics.append(
                Diagnostic(
                    "warning",
                    "no PyMechanical import or Mechanical scripting markers "
                    "(ExtAPI, Model.Analyses, ...) — is this a Mechanical script?",
                )
            )

        ok = not any(d.level == "error" for d in diagnostics)
        return LintResult(ok=ok, diagnostics=diagnostics)

    def connect(self) -> ConnectionInfo:
        installs = self.detect_installed()
        if not installs:
            return ConnectionInfo(
                solver="mechanical",
                version=None,
                status="not_installed",
                message="Ansys Mechanical not found",
            )
        top = installs[0]
        pm = _try_import_pymechanical()
        if pm is None:
            return ConnectionInfo(
                solver="mechanical",
                version=top.version,
                status="error",
                message=(
                    f"Ansys Mechanical {top.version} found at {top.path}, "
                    "but ansys-mechanical-core SDK is not installed. "
                    "Install with: uv pip install ansys-mechanical-core"
                ),
                solver_version=top.version,
            )
        return ConnectionInfo(
            solver="mechanical",
            version=top.version,
            status="ok",
            message=(
                f"Ansys Mechanical {top.version} at {top.path} "
                f"(PyMechanical {pm.__version__})"
            ),
            solver_version=top.version,
        )

    def parse_output(self, stdout: str) -> dict:
        """Extract the last JSON line from stdout, if any.

        PyMechanical's ``run_python_script`` returns the result of the
        last expression as a string. Our snippet convention is to emit
        ``json.dumps({...})`` as the last expression so both the return
        value *and* stdout carry the structured result.
        """
        if not stdout or not stdout.strip():
            return {}
        for line in reversed(stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        return {}

    def run_file(self, script: Path) -> RunResult:
        """Execute a Mechanical script file via the SDK.

        Uses ``run_python_script_from_file`` on a fresh transient session
        when no session is active. If the caller has already launched a
        persistent session via :meth:`launch`, the existing client is
        reused.
        """
        pm = _try_import_pymechanical()
        if pm is None:
            raise RuntimeError(
                "ansys-mechanical-core not installed. "
                "Install with: uv pip install ansys-mechanical-core"
            )

        installs = self.detect_installed()
        if not installs:
            raise RuntimeError(
                "Ansys Mechanical not found. Install it or set AWP_ROOTxxx."
            )
        top = installs[0]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")

        client_owned = False
        if self._client is None:
            self._client = pm.launch_mechanical(
                version=_version_code(top.version),
                batch=False,
                cleanup_on_exit=False,
            )
            client_owned = True

        t0 = time.time()
        try:
            out = self._client.run_python_script_from_file(str(script.resolve()))
            stdout = out if isinstance(out, str) else str(out or "")
            return RunResult(
                exit_code=0,
                stdout=stdout,
                stderr="",
                duration_s=round(time.time() - t0, 4),
                script=str(script),
                solver=self.name,
                timestamp=timestamp,
            )
        except Exception as e:
            return RunResult(
                exit_code=1,
                stdout="",
                stderr=f"{type(e).__name__}: {e}",
                duration_s=round(time.time() - t0, 4),
                script=str(script),
                solver=self.name,
                timestamp=timestamp,
            )
        finally:
            if client_owned:
                try:
                    self._client.exit()
                except Exception:
                    pass
                self._client = None

    def detect_installed(self) -> list[SolverInstall]:
        installs: list[SolverInstall] = []
        seen: set[str] = set()

        # Strategy 1: ansys-tools-path (official Ansys discovery)
        try:
            from ansys.tools.path import find_mechanical as _find
            result = _find()
            if result and result[0]:
                exe_path, version_float = result
                # exe = .../vNNN/aisol/bin/winx64/AnsysWBU.exe
                exe = Path(exe_path)
                # install root is .../vNNN
                root = exe.parent.parent.parent.parent
                version = self._extract_version(Path(root.name)) or f"{version_float:.1f}"
                resolved = str(root.resolve())
                if resolved not in seen:
                    seen.add(resolved)
                    installs.append(SolverInstall(
                        name="mechanical",
                        version=version,
                        path=str(root),
                        source="ansys-tools-path",
                        extra={"exe": str(exe)},
                    ))
        except Exception:
            pass

        # Strategy 2: AWP_ROOTxxx env vars
        for key, val in os.environ.items():
            m = _AWP_ROOT_RE.match(key)
            if m and val:
                p = Path(val)
                if not p.is_dir():
                    continue
                resolved = str(p.resolve())
                if resolved in seen:
                    continue
                exe = p / "aisol" / "bin" / "winx64" / "AnsysWBU.exe"
                if not exe.exists():
                    continue
                version = self._extract_version(Path(p.name))
                if version:
                    seen.add(resolved)
                    installs.append(SolverInstall(
                        name="mechanical",
                        version=version,
                        path=str(p),
                        source=f"env:{key}",
                        extra={"exe": str(exe)},
                    ))

        # Strategy 3: default install dirs (Windows)
        if os.name == "nt":
            for base in [
                Path("C:/Program Files/ANSYS Inc"),
                Path("C:/Program Files/Ansys Inc"),
                Path("E:/Program Files/ANSYS Inc"),
                Path("D:/Program Files/ANSYS Inc"),
            ]:
                if not base.is_dir():
                    continue
                for candidate in sorted(base.iterdir(), reverse=True):
                    if not candidate.is_dir() or not candidate.name.startswith("v"):
                        continue
                    resolved = str(candidate.resolve())
                    if resolved in seen:
                        continue
                    exe = candidate / "aisol" / "bin" / "winx64" / "AnsysWBU.exe"
                    if not exe.exists():
                        continue
                    version = self._extract_version(Path(candidate.name))
                    if version:
                        seen.add(resolved)
                        installs.append(SolverInstall(
                            name="mechanical",
                            version=version,
                            path=str(candidate),
                            source=f"default-path:{base}",
                            extra={"exe": str(exe)},
                        ))

        installs.sort(key=lambda i: i.version, reverse=True)
        return installs

    # ── Persistent session ─────────────────────────────────────────

    @property
    def supports_session(self) -> bool:
        return True

    @property
    def is_connected(self) -> bool:
        return self._client is not None

    def launch(
        self,
        mode: str = "mechanical",
        ui_mode: str = "gui",
        port: int | None = None,
        processors: int = 2,
        **kwargs,
    ) -> dict:
        """Start a Mechanical session with a **visible GUI window**.

        Observation commands depend on the GUI: sim's ``screenshot``
        endpoint grabs the desktop, so Mechanical must be batch=False.
        Set ``ui_mode="batch"`` only for headless smoke tests where
        screenshots are not needed.
        """
        if self._client is not None:
            raise RuntimeError("Mechanical session already active — disconnect first")

        pm = _try_import_pymechanical()
        if pm is None:
            raise RuntimeError(
                "ansys-mechanical-core not installed. "
                "Install with: uv pip install ansys-mechanical-core"
            )

        installs = self.detect_installed()
        if not installs:
            raise RuntimeError("Ansys Mechanical not found")
        top = installs[0]

        batch = (ui_mode == "batch")
        version_int = _version_code(top.version)
        launch_kwargs = dict(
            version=version_int,
            batch=batch,
            cleanup_on_exit=False,
        )
        # Ansys < 24.2 does not support secure gRPC — must be insecure.
        if version_int < 242:
            launch_kwargs["transport_mode"] = "insecure"
        if port is not None:
            launch_kwargs["port"] = port

        log.info(
            "Launching Mechanical %s (batch=%s) via PyMechanical %s",
            top.version, batch, pm.__version__,
        )
        self._client = pm.launch_mechanical(**launch_kwargs)
        self._client.wait_till_mechanical_is_ready(wait_time=120)

        self._session_id = str(uuid.uuid4())
        self._mode = mode
        self._ui_mode = ui_mode
        self._run_count = 0
        self._version = top.version
        self._launched_at = time.time()

        return {
            "ok": True,
            "session_id": self._session_id,
            "mode": mode,
            "ui_mode": ui_mode,
            "version": top.version,
            "backend": "pymechanical",
            "batch": batch,
        }

    def _dispatch(self, code: str, label: str = "snippet") -> dict:
        """Execute a Mechanical scripting snippet (no probes)."""
        if self._client is None:
            raise RuntimeError("No active Mechanical session — call launch() first")

        started = time.time()
        ok = True
        error = None
        stdout = ""

        try:
            result_str = self._client.run_python_script(code)
            stdout = result_str if isinstance(result_str, str) else str(result_str or "")
        except Exception as e:
            ok = False
            error = f"{type(e).__name__}: {e}"

        self._run_count += 1
        return {
            "ok": ok,
            "label": label,
            "stdout": stdout,
            "stderr": "",
            "error": error,
            "result": self.parse_output(stdout) if stdout else None,
            "elapsed_s": round(time.time() - started, 4),
        }

    def run(self, code: str, label: str = "snippet") -> dict:
        """Execute a snippet and attach inspect diagnostics."""
        from sim.inspect import InspectCtx, collect_diagnostics       # noqa: PLC0415

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
            stdout=result.get("stdout", ""),
            stderr=result.get("error", "") or "",  # error string → stderr slot
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

    def query(self, name: str) -> dict:
        """Session-level queries.

        ``session.summary`` is local metadata (cheap, no round-trip).
        ``mechanical.project_directory`` / ``mechanical.files`` /
        ``mechanical.product_info`` round-trip to the live session.
        """
        if name == "session.summary":
            return {
                "session_id": self._session_id,
                "mode": self._mode,
                "ui_mode": self._ui_mode,
                "connected": self.is_connected,
                "run_count": self._run_count,
                "version": self._version,
                "backend": "pymechanical",
                "launched_at": self._launched_at,
            }
        if not self.is_connected:
            raise RuntimeError(f"query '{name}' needs an active session")
        if name == "mechanical.product_info":
            try:
                return {"product_info": self._client.get_product_info()}
            except Exception as e:
                return {"error": str(e)}
        if name == "mechanical.files":
            try:
                return {"files": list(self._client.list_files())}
            except Exception as e:
                return {"error": str(e)}
        if name == "mechanical.project_directory":
            try:
                # project_directory is a property on newer clients,
                # fall back to running the query inside Mechanical
                code = "ExtAPI.DataModel.Project.ProjectDirectory"
                pd = self._client.run_python_script(code)
                return {"project_directory": pd}
            except Exception as e:
                return {"error": str(e)}
        raise ValueError(f"unknown query: {name}")

    def disconnect(self, **kwargs) -> None:
        if self._client is None:
            return
        try:
            # Clear project state before exit to prevent the "save
            # changes?" dialog from blocking shutdown in GUI mode.
            try:
                self._client.run_python_script(
                    "ExtAPI.DataModel.Project.New()"
                )
            except Exception:
                pass  # best-effort — if it fails, exit will pop the dialog

            # Start a background thread to dismiss any remaining dialog
            dismiss_thread = self._start_dialog_dismisser()
            self._client.exit()
        except Exception as e:
            log.warning("Mechanical exit() raised: %s", e)
        finally:
            if dismiss_thread is not None:
                self._stop_dialog_dismisser(dismiss_thread)
            self._client = None
            self._session_id = None
            self._mode = None
            self._ui_mode = None
            self._run_count = 0
            self._version = None
            self._launched_at = None

    @staticmethod
    def _start_dialog_dismisser():
        """Spawn a background thread that dismisses modal dialogs."""
        import subprocess
        import threading

        stop_flag = threading.Event()

        def _loop():
            ps = (
                'Add-Type @"\n'
                "using System; using System.Runtime.InteropServices;\n"
                "public class W {\n"
                '  [DllImport(\"user32.dll\")] public static extern IntPtr FindWindow(string c, string t);\n'
                '  [DllImport(\"user32.dll\")] public static extern bool SetForegroundWindow(IntPtr h);\n'
                '  [DllImport(\"user32.dll\")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);\n'
                "}\n"
                '"@\n'
                "$h = [W]::FindWindow('#32770', 'Ansys Mechanical')\n"
                "if ($h -ne [IntPtr]::Zero) {\n"
                "  [W]::SetForegroundWindow($h)\n"
                "  Start-Sleep -Milliseconds 200\n"
                "  Add-Type -AssemblyName System.Windows.Forms\n"
                "  [System.Windows.Forms.SendKeys]::SendWait('n')\n"
                "}\n"
                "$h2 = [W]::FindWindow('#32770', 'Script Error')\n"
                "if ($h2 -ne [IntPtr]::Zero) {\n"
                "  [W]::PostMessage($h2, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)\n"
                "}\n"
            )
            while not stop_flag.is_set():
                try:
                    subprocess.run(
                        ["powershell", "-Command", ps],
                        capture_output=True, timeout=10,
                    )
                except Exception:
                    pass
                stop_flag.wait(2)

        t = threading.Thread(target=_loop, daemon=True)
        t._stop_flag = stop_flag  # type: ignore[attr-defined]
        t.start()
        return t

    @staticmethod
    def _stop_dialog_dismisser(t):
        if hasattr(t, "_stop_flag"):
            t._stop_flag.set()
        t.join(timeout=5)

    # ── File transfer (SDK pass-through) ───────────────────────────

    def upload(self, local_path: str) -> dict:
        if self._client is None:
            raise RuntimeError("No active session")
        self._client.upload(file_name=local_path)
        return {"ok": True, "uploaded": local_path}

    def download(self, remote_name: str, target_dir: str) -> dict:
        if self._client is None:
            raise RuntimeError("No active session")
        paths = self._client.download(files=remote_name, target_dir=target_dir)
        return {"ok": True, "paths": list(paths)}

    # ── Helpers ────────────────────────────────────────────────────

    @staticmethod
    def _extract_version(dir_name: Path) -> str | None:
        """v241 → '24.1'."""
        m = _VERSION_DIR_RE.search(str(dir_name))
        if m:
            return f"{m.group(1)}.{m.group(2)}"
        return None
