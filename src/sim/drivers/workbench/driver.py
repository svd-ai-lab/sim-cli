"""Ansys Workbench driver for sim.

Dual-mode: SDK Persistent (preferred) with GUI Automation fallback.

Execution priority:
  1. PyWorkbench SDK (``ansys-workbench-core``) — persistent session via gRPC.
     If SDK import or launch fails, automatically falls back to (2).
  2. RunWB2.exe batch mode (``RunWB2 -B -R journal.wbjn``) — one-shot GUI
     automation. Works even when the SDK is not installed or incompatible.

IronPython stdout convention: journals write JSON to %TEMP%/sim_wb_result.json
because RunWB2 (and the SDK's IronPython sandbox) do not pipe stdout.

Detection chain: AWP_ROOTxxx env vars → PATH probe → default install dirs.
"""
from __future__ import annotations

import ast
import json
import logging
import os
import re
import shutil
import subprocess
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

from sim.runner import detect_output_errors

log = logging.getLogger(__name__)

# Workbench / IronPython error patterns (supplement generic ones)
_WB_ERROR_PATTERNS = [
    re.compile(r"Framework error caught", re.IGNORECASE),
    re.compile(r"ScriptingException:", re.IGNORECASE),
    re.compile(r"MissingMemberException:", re.IGNORECASE),
    re.compile(r"AttributeError:", re.IGNORECASE),
    re.compile(r"出现意外错误", re.IGNORECASE),  # CJK: "unexpected error"
]

# TextStreamRulesProbe rules — same patterns translated to probe format.
# Workbench stderr is always "" so we scan stdout instead (#6 position).
_WB_STDOUT_RULES: list[dict] = [
    {"pattern": r"Framework error caught", "severity": "error",
     "code": "wb.scripting.framework_error"},
    {"pattern": r"ScriptingException:", "severity": "error",
     "code": "wb.scripting.exception"},
    {"pattern": r"MissingMemberException:", "severity": "error",
     "code": "wb.scripting.missing_member"},
    {"pattern": r"AttributeError:", "severity": "warning",
     "code": "wb.scripting.attribute_error"},
    {"pattern": r"出现意外错误", "severity": "error",
     "code": "wb.unexpected_error"},
]


def _default_workbench_probes(enable_gui: bool = False) -> list:
    """Workbench probe list — generic_probes() + Workbench-specific channels.

    Generic (via generic_probes()):
      #1  ProcessMetaProbe      #1+ RuntimeTimeoutProbe
      #3  StdoutJsonTailProbe   #3+ PythonTracebackProbe   #9 WorkdirDiffProbe

    Workbench-specific:
      #6  TextStreamRulesProbe(wb:stdout) — Framework/Scripting errors on stdout
          (Workbench stderr is always "" — both SDK and RunWB2 suppress it)
      #5  DomainExceptionMapProbe         — post-processor
      #8a GuiDialogProbe                  — optional, only if enable_gui
      #8b ScreenshotProbe                 — optional, only if enable_gui

    NOT wired:
      #2  stderr  — always "" for Workbench
      #4  SdkAttributeProbe — dual-backend state is complex to inspect
      #7  log file — no per-session log
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
            source="wb:stdout",
            text_selector=lambda ctx: ctx.stdout,
            rules=_WB_STDOUT_RULES,
        ),
        _g["stdout-json-tail"],                                        # #3  通用
        _g["python-traceback"],                                        # #3+ 通用
        DomainExceptionMapProbe(),                                      # #5  post-processor
    ]
    if enable_gui:
        probes.append(GuiDialogProbe(                                  # #8a
            process_name_substrings=("AnsysWBU", "Workbench", "RunWB2"),
            code_prefix="wb.gui"))
        probes.append(ScreenshotProbe(                                 # #8b
            filename_prefix="wb_shot",
            process_name_substrings=("AnsysWBU", "Workbench")))
    probes.append(_g["workdir-diff"])                                  # #9  通用（始终最后）
    return probes


def _detect_wb_errors(stdout: str, stderr: str) -> list[str]:
    """Detect errors in Workbench output — generic + WB-specific patterns."""
    errors = detect_output_errors(stdout, stderr)
    for text, source in [(stderr, "stderr"), (stdout, "stdout")]:
        if not text:
            continue
        for pat in _WB_ERROR_PATTERNS:
            m = pat.search(text)
            if m:
                line = m.group(0)[:200]
                if not any(line in e for e in errors):
                    errors.append(f"[{source}] {line}")
    return errors

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_WB_JOURNAL_MARKERS = (
    "SetScriptVersion",
    "GetTemplate",
    "CreateSystem",
    "GetModel",
    "system1",
)

_WB_PY_IMPORT = re.compile(
    r"^\s*(import\s+ansys\.workbench|from\s+ansys\.workbench\b)", re.MULTILINE
)

_AWP_ROOT_RE = re.compile(r"^AWP_ROOT(\d{3})$")
_VERSION_DIR_RE = re.compile(r"v(\d{2})(\d)$")

_RESULT_FILE = Path(os.environ.get("TEMP", "C:/Temp")) / "sim_wb_result.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _version_code(version_str: str) -> str:
    """'24.1' → '241'."""
    return version_str.replace(".", "")


def _try_import_pyworkbench():
    """Return the ``ansys.workbench.core`` module or None."""
    try:
        import ansys.workbench.core as pywb  # noqa: F811
        return pywb
    except ImportError:
        return None


def _kill_process_tree(pid: int) -> None:
    """Kill a process and all its children (AnsysFWW, ansyscl, etc.)."""
    try:
        import signal
        # Windows: taskkill /T kills the entire process tree
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, timeout=10,
            )
        else:
            os.kill(pid, signal.SIGTERM)
    except Exception:
        pass


def _exit_workbench(wb) -> None:
    """Shut down a Workbench client and its entire process tree.

    Strategy:
    1. Try SDK-level exit (clean shutdown)
    2. If that fails or leaves children, kill the process tree by PID
    Never raises — disconnect must be idempotent and safe.
    """
    if wb is None:
        return

    # Grab the PID before attempting exit — we may need it for tree kill
    pid = None
    for attr in ("_process", "process"):
        proc = getattr(wb, attr, None)
        if proc is not None and hasattr(proc, "pid"):
            pid = proc.pid
            break

    # Try SDK-level exit
    for method in ("exit", "close"):
        fn = getattr(wb, method, None)
        if fn is not None and callable(fn):
            try:
                fn()
            except Exception:
                pass

    # Kill the entire process tree (RunWB2 + AnsysFWW + ansyscl children)
    if pid is not None:
        _kill_process_tree(pid)


def _clear_result_file() -> None:
    if _RESULT_FILE.exists():
        _RESULT_FILE.unlink()


def _read_result_file() -> str | None:
    """Read and return the content of the result file, or None."""
    if not _RESULT_FILE.exists():
        return None
    try:
        return _RESULT_FILE.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

class WorkbenchDriver:
    """Driver for Ansys Workbench — SDK first, RunWB2 fallback."""

    def __init__(self):
        self._client: Any = None          # PyWorkbench client or None
        self._session_id: str | None = None
        self._mode: str | None = None
        self._run_count: int = 0
        self._version: str | None = None
        self._backend: str | None = None  # "pyworkbench" | "runwb2"
        self._sim_dir: Path = Path(os.environ.get("SIM_DIR") or (Path.cwd() / ".sim"))
        self.probes: list = _default_workbench_probes(enable_gui=False)

    # ── DriverProtocol ──────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "workbench"

    def detect(self, script: Path) -> bool:
        if not script.exists():
            return False
        ext = script.suffix.lower()
        if ext == ".wbjn":
            return True
        if ext == ".py":
            try:
                text = script.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                return False
            return bool(_WB_PY_IMPORT.search(text))
        return False

    def lint(self, script: Path) -> LintResult:
        diagnostics: list[Diagnostic] = []
        ext = script.suffix.lower()

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

        if ext == ".wbjn":
            if not any(m in text for m in _WB_JOURNAL_MARKERS):
                diagnostics.append(
                    Diagnostic("warning", "no Workbench API calls found (SetScriptVersion, GetTemplate, etc.)")
                )
        elif ext == ".py":
            if not _WB_PY_IMPORT.search(text):
                diagnostics.append(
                    Diagnostic("error", "missing 'import ansys.workbench' or 'from ansys.workbench'")
                )

        ok = not any(d.level == "error" for d in diagnostics)
        return LintResult(ok=ok, diagnostics=diagnostics)

    def connect(self) -> ConnectionInfo:
        installs = self.detect_installed()
        if not installs:
            return ConnectionInfo(
                solver="workbench", version=None,
                status="not_installed",
                message="Ansys Workbench not found",
            )
        top = installs[0]
        pywb = _try_import_pyworkbench()
        sdk_note = f" (PyWorkbench {pywb.__version__})" if pywb else " (SDK not installed — RunWB2 fallback)"
        return ConnectionInfo(
            solver="workbench",
            version=top.version,
            status="ok",
            message=f"Ansys Workbench {top.version} at {top.path}{sdk_note}",
            solver_version=top.version,
        )

    def parse_output(self, stdout: str) -> dict:
        if not stdout or not stdout.strip():
            return {}
        for line in reversed(stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        return {}

    def run_file(self, script: Path) -> RunResult:
        """Execute a Workbench journal. Try SDK first, fall back to RunWB2."""
        installs = self.detect_installed()
        if not installs:
            raise RuntimeError(
                "Ansys Workbench not found. Install it or set AWP_ROOTxxx env var."
            )
        top = installs[0]

        # Attempt 1: SDK
        pywb = _try_import_pyworkbench()
        if pywb is not None:
            result = self._run_file_sdk(script, top, pywb)
            if result is not None:
                return result
            log.warning("SDK execution failed, falling back to RunWB2")

        # Attempt 2: RunWB2
        return self._run_file_runwb2(script, top)

    def detect_installed(self) -> list[SolverInstall]:
        installs: list[SolverInstall] = []
        seen: set[str] = set()

        # Strategy 1: AWP_ROOTxxx env vars
        for key, val in os.environ.items():
            m = _AWP_ROOT_RE.match(key)
            if m and val:
                p = Path(val)
                resolved = str(p.resolve()) if p.exists() else str(p)
                if resolved not in seen and p.is_dir():
                    seen.add(resolved)
                    version = self._extract_version(Path(p.name))
                    if version and (p / "Framework" / "bin" / "Win64" / "RunWB2.exe").exists():
                        installs.append(SolverInstall(
                            name="workbench",
                            version=version,
                            path=str(p),
                            source=f"env:{key}",
                        ))

        # Strategy 2: PATH probe
        which = shutil.which("RunWB2") or shutil.which("RunWB2.exe")
        if which:
            wb_path = Path(which).resolve()
            root = wb_path.parent.parent.parent.parent
            resolved = str(root.resolve())
            if resolved not in seen:
                seen.add(resolved)
                version = self._extract_version(Path(root.name))
                if version:
                    installs.append(SolverInstall(
                        name="workbench",
                        version=version,
                        path=str(root),
                        source="which:RunWB2",
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
                    seen.add(resolved)
                    version = self._extract_version(Path(candidate.name))
                    if version:
                        runwb2 = candidate / "Framework" / "bin" / "Win64" / "RunWB2.exe"
                        if runwb2.exists():
                            installs.append(SolverInstall(
                                name="workbench",
                                version=version,
                                path=str(candidate),
                                source=f"default-path:{base}",
                            ))

        installs.sort(key=lambda i: i.version, reverse=True)
        return installs

    # ── Persistent session ─────────────────────────────────────────

    @property
    def supports_session(self) -> bool:
        return True

    @property
    def is_connected(self) -> bool:
        return self._client is not None or self._backend == "runwb2"

    def launch(self, mode: str = "workbench", ui_mode: str = "gui", processors: int = 2, **kwargs) -> dict:
        """Start a Workbench session. SDK first, RunWB2 fallback."""
        if self._client is not None:
            raise RuntimeError("Session already active — disconnect first")

        installs = self.detect_installed()
        if not installs:
            raise RuntimeError("Ansys Workbench not found")

        top = installs[0]
        release = _version_code(top.version)

        # Attempt 1: SDK
        pywb = _try_import_pyworkbench()
        if pywb is not None:
            try:
                self._client = pywb.launch_workbench(release=release)
                self._backend = "pyworkbench"
                log.info("Workbench session launched via PyWorkbench SDK")
            except Exception as e:
                log.warning("SDK launch failed (%s), falling back to RunWB2", e)
                self._client = None

        # Attempt 2: RunWB2 fallback
        if self._client is None:
            runwb2 = self._find_runwb2(Path(top.path))
            if runwb2 is None:
                raise RuntimeError(f"RunWB2.exe not found in {top.path}")
            self._client = {"runwb2": str(runwb2), "version": top.version}
            self._backend = "runwb2"
            log.info("Workbench session launched via RunWB2 fallback")

        self._session_id = str(uuid.uuid4())
        self._mode = mode
        self._run_count = 0
        self._version = top.version

        return {
            "ok": True,
            "session_id": self._session_id,
            "mode": mode,
            "ui_mode": ui_mode,
            "version": top.version,
            "backend": self._backend,
        }

    def _dispatch(self, code: str, label: str = "snippet") -> dict:
        """Execute a script snippet against the live session (no probes)."""
        if self._client is None and self._backend != "runwb2":
            raise RuntimeError("No active session — call launch() first")

        _clear_result_file()
        started = time.time()

        if self._backend == "pyworkbench":
            ok, stdout, error = self._exec_sdk(code)
        else:
            ok, stdout, error = self._exec_runwb2(code)

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
        if name == "session.summary":
            return {
                "session_id": self._session_id,
                "mode": self._mode,
                "connected": self.is_connected,
                "run_count": self._run_count,
                "version": self._version,
                "backend": self._backend,
            }
        raise ValueError(f"unknown query: {name}")

    def disconnect(self, **kwargs) -> None:
        if self._client is None and self._backend is None:
            return
        # Actually shut down the Workbench process
        if self._backend == "pyworkbench" and self._client is not None:
            _exit_workbench(self._client)
        self._client = None
        self._session_id = None
        self._mode = None
        self._run_count = 0
        self._version = None
        self._backend = None

    # ── SDK execution ──────────────────────────────────────────────

    def _run_file_sdk(self, script: Path, install: SolverInstall, pywb) -> RunResult | None:
        """Try executing via SDK. Returns None on SDK-level failure."""
        release = _version_code(install.version)
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        _clear_result_file()

        t0 = time.time()
        wb = None
        try:
            wb = pywb.launch_workbench(release=release)
            text = script.read_text(encoding="utf-8")
            result_str = wb.run_script_string(text, log_level="warning")
            stdout = result_str if isinstance(result_str, str) else str(result_str or "")
            stdout = self._append_result_file(stdout)

            # Analyze ALL output for errors — never blindly return exit_code=0
            errors = _detect_wb_errors(stdout, "")
            exit_code = 1 if errors else 0

            return RunResult(
                exit_code=exit_code, stdout=stdout, stderr="",
                duration_s=round(time.time() - t0, 4),
                script=str(script), solver=self.name, timestamp=timestamp,
                errors=errors,
            )
        except Exception as e:
            log.warning("SDK run_file failed: %s", e)
            return None
        finally:
            # One-shot: always close the Workbench process after run_file
            _exit_workbench(wb)

    def _exec_sdk(self, code: str) -> tuple[bool, str, str | None]:
        """Execute snippet via SDK session."""
        try:
            result_str = self._client.run_script_string(code, log_level="warning")
            stdout = result_str if isinstance(result_str, str) else str(result_str or "")
            stdout = self._append_result_file(stdout)
            errors = _detect_wb_errors(stdout, "")
            if errors:
                return False, stdout, "; ".join(errors)
            return True, stdout, None
        except Exception as e:
            return False, "", str(e)

    # ── RunWB2 fallback execution ──────────────────────────────────

    def _run_file_runwb2(self, script: Path, install: SolverInstall) -> RunResult:
        """Execute via RunWB2.exe batch mode."""
        runwb2 = self._find_runwb2(Path(install.path))
        if runwb2 is None:
            raise RuntimeError(f"RunWB2.exe not found in {install.path}")

        ext = script.suffix.lower()
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        _clear_result_file()

        t0 = time.time()
        if ext == ".wbjn":
            result = subprocess.run(
                [str(runwb2), "-B", "-R", str(script.resolve())],
                capture_output=True, text=True, timeout=600,
            )
        else:
            import sys
            result = subprocess.run(
                [sys.executable, str(script)],
                capture_output=True, text=True, timeout=600,
            )

        stdout = self._append_result_file(result.stdout)
        stderr = result.stderr or ""

        # Analyze ALL output — exit_code alone is unreliable for RunWB2
        errors = _detect_wb_errors(stdout, stderr)
        exit_code = result.returncode
        if exit_code == 0 and errors:
            exit_code = 1

        return RunResult(
            exit_code=exit_code, stdout=stdout, stderr=stderr,
            duration_s=round(time.time() - t0, 4),
            script=str(script), solver=self.name, timestamp=timestamp,
            errors=errors,
        )

    def _exec_runwb2(self, code: str) -> tuple[bool, str, str | None]:
        """Execute snippet via RunWB2 temp journal."""
        import tempfile
        runwb2 = self._client.get("runwb2", "") if isinstance(self._client, dict) else ""
        if not runwb2:
            return False, "", "No RunWB2 path in session"

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".wbjn", delete=False, encoding="utf-8",
        ) as f:
            f.write(code)
            tmp_path = f.name

        try:
            result = subprocess.run(
                [runwb2, "-B", "-R", tmp_path],
                capture_output=True, text=True, timeout=600,
            )
            stdout = self._append_result_file(result.stdout)
            stderr = result.stderr or ""
            errors = _detect_wb_errors(stdout, stderr)
            if result.returncode != 0 or errors:
                return False, stdout, "; ".join(errors) if errors else stderr
            return True, stdout, None
        except Exception as e:
            return False, "", str(e)
        finally:
            os.unlink(tmp_path)

    # ── Shared helpers ─────────────────────────────────────────────

    @staticmethod
    def _append_result_file(stdout: str) -> str:
        """Append result file content to stdout if it exists."""
        content = _read_result_file()
        if content:
            return (stdout + "\n" + content).strip()
        return stdout

    @staticmethod
    def _extract_version(dir_name: Path) -> str | None:
        """v241 → '24.1'."""
        m = _VERSION_DIR_RE.search(str(dir_name))
        if m:
            return f"{m.group(1)}.{m.group(2)}"
        return None

    @staticmethod
    def _find_runwb2(install_root: Path) -> Path | None:
        """Locate RunWB2.exe within an Ansys installation."""
        for name in ("RunWB2.exe", "runwb2.bat"):
            candidate = install_root / "Framework" / "bin" / "Win64" / name
            if candidate.exists():
                return candidate
        return None
