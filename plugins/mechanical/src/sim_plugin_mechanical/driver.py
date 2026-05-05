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
import traceback
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


def _safe_text(value: object, *, limit: int = 200) -> str | None:
    """Return a short ASCII-safe string for public diagnostics."""
    if value is None:
        return None
    text = str(value)
    text = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in text)
    return text[:limit]


def _safe_name(value: object) -> str | None:
    text = _safe_text(value)
    if not text:
        return None
    return Path(text.replace("\\", "/")).name or text


def _mechanical_ui_capabilities(ui_mode: str | None, batch: bool | None) -> dict:
    visible = not bool(batch) and ui_mode not in {"no_gui", "batch"}
    return {
        "visible_window_expected": visible,
        "screenshot_expected": visible,
        "sdk_gui_coupled": visible,
        "headless": bool(batch),
    }


class MechanicalArtifactProbe:
    """Describe new Mechanical solver/result artifacts in the sim workdir."""

    name = "mechanical-artifacts"

    def __init__(self, *, only_new: bool = True, max_files: int = 8) -> None:
        self.only_new = only_new
        self.max_files = max_files

    def applies(self, ctx) -> bool:
        if self.only_new and ctx.workdir_before is None:
            return False
        try:
            return Path(ctx.workdir).is_dir()
        except Exception:
            return False

    def probe(self, ctx):
        from sim.inspect import Diagnostic as RuntimeDiagnostic  # noqa: PLC0415
        from sim.inspect import ProbeResult  # noqa: PLC0415

        root = Path(ctx.workdir)
        before = set(ctx.workdir_before or [])
        candidates: list[Path] = []
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            rel = str(path.relative_to(root)).replace("\\", "/")
            if self.only_new and rel in before:
                continue
            low = path.name.lower()
            if (
                low.endswith(".rst")
                or low.endswith(".err")
                or low == "solve.out"
                or low.endswith(".csv")
            ):
                candidates.append(path)
        diagnostics = []
        for path in candidates[:self.max_files]:
            name = _safe_name(path.name)
            size = path.stat().st_size
            low = path.name.lower()
            extra = {"file_name": name, "size": size}
            if low.endswith(".rst"):
                diagnostics.append(RuntimeDiagnostic(
                    severity="info",
                    source="mechanical:artifact",
                    code="mechanical.result.rst_detected",
                    message="Mechanical result file detected",
                    extra=extra,
                ))
            elif low.endswith(".err"):
                tail = ""
                try:
                    tail = path.read_text(
                        encoding="utf-8", errors="replace"
                    )[-500:]
                except OSError:
                    tail = ""
                diagnostics.append(RuntimeDiagnostic(
                    severity="warning" if size else "info",
                    source="mechanical:artifact",
                    code="mechanical.solve.err_detected",
                    message="Mechanical solver error file detected",
                    extra={**extra, "tail": _safe_text(tail, limit=300)},
                ))
            elif low == "solve.out":
                diagnostics.append(RuntimeDiagnostic(
                    severity="info",
                    source="mechanical:artifact",
                    code="mechanical.solve.output_detected",
                    message="Mechanical solver output detected",
                    extra=extra,
                ))
            elif low.endswith(".csv"):
                diagnostics.append(RuntimeDiagnostic(
                    severity="info",
                    source="mechanical:artifact",
                    code="mechanical.result.csv_detected",
                    message="Mechanical exported data detected",
                    extra=extra,
                ))
        if len(candidates) > self.max_files:
            diagnostics.append(RuntimeDiagnostic(
                severity="warning",
                source="mechanical:artifact",
                code="mechanical.artifacts.truncated",
                message="Mechanical artifact diagnostics were truncated",
                extra={"reported": self.max_files, "total": len(candidates)},
            ))
        return ProbeResult(diagnostics=diagnostics)


def _default_mechanical_probes(enable_gui: bool = True) -> list:
    """Mechanical probe list — generic_probes() + optional GUI observation.

    No driver-layer semantic assertions: "what counts as an error" is the
    agent's job, not the driver's. Probes here only extract facts.
    enable_gui=True by default because Mechanical always launches with a
    visible GUI window (batch=False is the driver's policy); the GUI probes
    report which dialogs exist + a screenshot, without labelling any of
    them as errors.
    """
    from sim.inspect import (                                          # noqa: PLC0415
        GuiDialogProbe, ScreenshotProbe, generic_probes,
    )
    probes: list = list(generic_probes())
    probes.append(MechanicalArtifactProbe(only_new=True))
    if enable_gui:
        probes.append(GuiDialogProbe(
            process_name_substrings=("AnsysWBU", "Mechanical", "ANSYS"),
            code_prefix="mech.gui"))
        probes.append(ScreenshotProbe(
            filename_prefix="mech_shot",
            process_name_substrings=("AnsysWBU", "Mechanical", "ANSYS")))
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


def _build_launch_kwargs(top: SolverInstall, *, batch: bool, port: int | None = None) -> dict:
    """Build kwargs for ``pm.launch_mechanical`` with the secure-transport gate.

    Both the persistent-session ``launch()`` and one-shot ``run_file()`` paths
    must go through this helper so the ``SIM_MECHANICAL_INSECURE_TRANSPORT``
    escape hatch applies uniformly.
    """
    version_int = _version_code(top.version)
    kwargs: dict[str, Any] = dict(version=version_int, batch=batch, cleanup_on_exit=False)
    # Ansys < 24.2 has no secure-gRPC support. 25.2 RTM also lacks it without
    # SP03+ — allow forcing insecure via env var until upstream exposes a
    # reliable SP probe.
    if version_int < 242 or os.environ.get("SIM_MECHANICAL_INSECURE_TRANSPORT") == "1":
        kwargs["transport_mode"] = "insecure"
    if port is not None:
        kwargs["port"] = port
    return kwargs


def _launch_with_hint(pm, launch_kwargs: dict):
    """Call ``pm.launch_mechanical`` and translate secure-transport errors.

    When PyMechanical refuses to launch because the Ansys build lacks secure
    gRPC, append an actionable hint pointing at the env-var escape hatch.
    """
    try:
        return pm.launch_mechanical(**launch_kwargs)
    except Exception as e:
        if "secure transport" in str(e).lower():
            raise RuntimeError(
                f"{e}\n\n"
                "Hint: this Ansys release lacks secure-gRPC support "
                "(e.g. 25.2 RTM without SP03+). Set "
                "SIM_MECHANICAL_INSECURE_TRANSPORT=1 before launching "
                "`sim serve` or running `sim run mechanical`. "
                "See README troubleshooting for details."
            ) from e
        raise


def _find_ansys_pid(port: int | None = None, timeout_s: float = 2.0) -> int | None:
    """Best-effort: locate the AnsysWBU.exe PID for the just-launched session.

    Strategy:
      1. If ``port`` is known, find the process listening on it (most specific).
      2. Otherwise (or as fallback): the most recently started AnsysWBU.exe
         owned by the current user.

    Returns ``None`` if neither approach finds anything — the screenshot
    probe will degrade gracefully to its substring fallback.
    """
    try:
        import psutil  # noqa: PLC0415
    except ImportError:
        return None
    import time as _time  # noqa: PLC0415
    deadline = _time.time() + timeout_s
    while _time.time() < deadline:
        if port is not None:
            try:
                for c in psutil.net_connections(kind="tcp"):
                    if (c.laddr and c.laddr.port == port
                            and c.status == "LISTEN" and c.pid):
                        return c.pid
            except (psutil.AccessDenied, OSError):
                pass
        try:
            try:
                current_user = psutil.Process().username()
            except Exception:
                current_user = None
            candidates = []
            for p in psutil.process_iter(attrs=["pid", "name", "username", "create_time"]):
                info = p.info or {}
                name = (info.get("name") or "").lower()
                if not name.startswith("ansyswbu"):
                    continue
                if current_user and info.get("username") != current_user:
                    continue
                candidates.append(info)
            if candidates:
                candidates.sort(key=lambda i: i.get("create_time") or 0, reverse=True)
                return candidates[0]["pid"]
        except (psutil.AccessDenied, OSError):
            pass
        _time.sleep(0.05)
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
        self._batch: bool | None = None
        self._run_count: int = 0
        self._version: str | None = None
        self._launched_at: float | None = None
        self._target_pid: int | None = None
        self._last_run: dict | None = None
        self._last_error: str | None = None
        self._last_health: dict | None = None
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
                    f"Ansys Mechanical {top.version} was found, "
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
                f"Ansys Mechanical {top.version} "
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
            launch_kwargs = _build_launch_kwargs(top, batch=False)
            self._client = _launch_with_hint(pm, launch_kwargs)
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

    def _visible_window_summary(self) -> dict:
        if self._batch:
            return {"available": False, "match_count": 0, "processes": []}
        try:
            from sim.gui import GuiController  # noqa: PLC0415
            gui = GuiController(
                process_name_substrings=("AnsysWBU", "Mechanical", "ANSYS"),
                workdir=str(self._sim_dir),
            )
            if not gui.available:
                return {"available": False, "match_count": 0, "processes": []}
            data = gui.list_windows()
        except Exception as exc:  # noqa: BLE001 - GUI support is optional
            return {
                "available": False,
                "match_count": 0,
                "processes": [],
                "error": type(exc).__name__,
            }
        if not data.get("ok"):
            return {
                "available": True,
                "match_count": 0,
                "processes": [],
                "error": _safe_text(data.get("error")),
            }
        windows = data.get("windows", []) or []
        if self._target_pid is not None:
            windows = [
                w for w in windows
                if int(w.get("pid", -1)) == int(self._target_pid)
            ]
        processes = sorted({
            _safe_text(w.get("proc"), limit=80) or ""
            for w in windows if w.get("proc")
        })
        return {
            "available": True,
            "match_count": len(windows),
            "processes": [p for p in processes if p],
            "has_visible_window": bool(windows),
            "target_pid_known": self._target_pid is not None,
        }

    def _client_health_roundtrip(self) -> tuple[bool | None, str | None]:
        if self._client is None:
            return False, "not connected"
        verify = getattr(self._client, "verify_valid_connection", None)
        if callable(verify):
            try:
                value = verify()
                return True if value is None else bool(value), None
            except Exception as exc:  # noqa: BLE001 - SDK exceptions vary
                return False, f"{type(exc).__name__}: {exc}"
        try:
            value = self._client.run_python_script("1")
            return str(value).strip() in {"1", "1.0"} or value is not None, None
        except Exception as exc:  # noqa: BLE001 - SDK exceptions vary
            return False, f"{type(exc).__name__}: {exc}"

    def _product_version(self) -> str | None:
        if self._client is None:
            return None
        try:
            info = str(self._client.get_product_info())
        except Exception:
            return None
        match = re.search(r"Product Version:\s*([0-9.]+)", info)
        return match.group(1) if match else None

    def _gui_coupling_diagnostics(self) -> list:
        from sim.inspect import Diagnostic as RuntimeDiagnostic  # noqa: PLC0415

        diagnostics = []
        if self._batch:
            diagnostics.append(RuntimeDiagnostic(
                severity="warning",
                source="mechanical:gui",
                code="mechanical.gui.batch_no_screenshot",
                message="Mechanical is running without a visible GUI; screenshot confirmation is unavailable",
                extra={"ui_mode": self._ui_mode, "batch": self._batch},
            ))
            return diagnostics
        windows = self._visible_window_summary()
        if self._ui_mode == "gui" and windows.get("available") and not windows.get("has_visible_window"):
            diagnostics.append(RuntimeDiagnostic(
                severity="warning",
                source="mechanical:gui",
                code="mechanical.gui.window_not_found",
                message="No visible Mechanical window matched the live session",
                extra={"target_pid_known": self._target_pid is not None},
            ))
        return diagnostics

    def health(self) -> dict:
        """Best-effort live-session health without raw product or entitlement text."""
        alive, error = self._client_health_roundtrip()
        connected = self.is_connected and alive is not False
        if not self.is_connected:
            code = "mechanical.session.disconnected"
            message = "Mechanical session is not connected"
        elif alive is False:
            code = "mechanical.sdk.health_failed"
            message = "Mechanical SDK health check failed"
        else:
            code = "mechanical.session.connected"
            message = "Mechanical session is connected"
        diagnostics = [d.to_dict() for d in self._gui_coupling_diagnostics()]
        health = {
            "ok": connected,
            "connected": connected,
            "code": code,
            "message": message,
            "session_id": self._session_id,
            "backend": "pymechanical" if self._client is not None else None,
            "run_count": self._run_count,
            "ui_mode": self._ui_mode,
            "batch": self._batch,
            "ui_capabilities": _mechanical_ui_capabilities(self._ui_mode, self._batch),
            "last_error": _safe_text(self._last_error or error),
            "version": self._version,
            "product_version": self._product_version(),
            "target_pid_known": self._target_pid is not None,
            "windows": self._visible_window_summary(),
            "diagnostics": diagnostics,
        }
        self._last_health = health
        return health

    def launch(
        self,
        mode: str = "mechanical",
        ui_mode: str = "gui",
        port: int | None = None,
        processors: int = 2,
        **kwargs,
    ) -> dict:
        """Start a Mechanical session.

        ``ui_mode``:
            * ``"gui"`` (default) — visible GUI window. Required for
              ``sim screenshot`` and other observation probes.
            * ``"no_gui"`` (alias ``"batch"``) — headless. Faster startup,
              but no screenshot support. Use only for headless smoke tests.

        ``"no_gui"`` is the canonical CLI value (matches sim-cli's
        ``--ui-mode`` choice); ``"batch"`` is accepted for backward compat.
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

        batch = ui_mode in ("batch", "no_gui")
        self.probes = _default_mechanical_probes(enable_gui=not batch)
        launch_kwargs = _build_launch_kwargs(top, batch=batch, port=port)

        log.info(
            "Launching Mechanical %s (batch=%s) via PyMechanical %s",
            top.version, batch, pm.__version__,
        )
        self._client = _launch_with_hint(pm, launch_kwargs)
        self._client.wait_till_mechanical_is_ready(wait_time=120)

        # Pin GUI probes to this exact AnsysWBU.exe PID so screenshots
        # don't capture other "ansys"-named windows that happen to be
        # foreground (terminals, helper tools, etc.). Best-effort; if PID
        # discovery fails, probes fall back to substring matching.
        client_port = getattr(self._client, "_port", None)
        target_pid = _find_ansys_pid(port=client_port)
        if target_pid is not None:
            for p in self.probes:
                if hasattr(p, "target_pid"):
                    p.target_pid = target_pid
            self._target_pid = target_pid
            log.info("Pinned GUI probes to AnsysWBU pid=%s (port=%s)",
                     target_pid, client_port)
        else:
            self._target_pid = None
            log.info("Could not discover AnsysWBU pid; "
                     "probes will use substring matching")

        self._session_id = str(uuid.uuid4())
        self._mode = mode
        self._ui_mode = ui_mode
        self._batch = batch
        self._run_count = 0
        self._version = top.version
        self._launched_at = time.time()
        self._last_run = None
        self._last_error = None
        self._last_health = self.health()

        return {
            "ok": True,
            "session_id": self._session_id,
            "mode": mode,
            "ui_mode": ui_mode,
            "version": top.version,
            "backend": "pymechanical",
            "batch": batch,
            "ui_capabilities": _mechanical_ui_capabilities(ui_mode, batch),
            "health": self._last_health,
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

    @staticmethod
    def _looks_like_solve_attempt(code: str, label: str) -> bool:
        text = f"{label}\n{code}".lower()
        return "solve" in text or ".solve(" in text

    @staticmethod
    def _solve_incomplete_statuses(state: dict) -> list[str]:
        statuses: list[str] = []
        for analysis in state.get("analyses", []) or []:
            status = _safe_text(analysis.get("solution_status") or "")
            normalized = status.lower().replace(" ", "")
            if normalized in {"solverequired", "notsolved", "failed", "error"}:
                statuses.append(status or "unknown")
        return statuses

    def _solve_state(self) -> dict:
        code = r'''
import json

def safe(obj):
    try:
        s = str(obj)
        return "".join(c if ord(c) < 128 else "?" for c in s)
    except:
        return "unknown"

analyses = []
for i, a in enumerate(Model.Analyses):
    item = {"index": i}
    try:
        item["type"] = safe(a.AnalysisType)
    except:
        item["type"] = "unknown"
    try:
        item["solution_status"] = safe(a.Solution.Status)
    except:
        item["solution_status"] = "unknown"
    try:
        item["solution_result_count"] = len(a.Solution.Children)
    except:
        item["solution_result_count"] = None
    try:
        item["result_file_available"] = bool(a.ResultFileName)
    except:
        item["result_file_available"] = False
    analyses.append(item)

json.dumps({"ok": True, "analyses": analyses, "analysis_count": len(analyses)})
'''
        return self._run_json_query(code)

    def run(
        self,
        code: str,
        label: str = "snippet",
        timeout_s: float | None = None,
    ) -> dict:
        """Execute a snippet and attach inspect diagnostics."""
        from sim.inspect import InspectCtx, collect_diagnostics       # noqa: PLC0415
        from sim._timeout import DEFAULT_TIMEOUT_S, call_with_timeout  # noqa: PLC0415

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
        timeout_budget = DEFAULT_TIMEOUT_S if timeout_s is None else timeout_s
        t_result = call_with_timeout(
            lambda: self._dispatch(code, label),
            timeout_s=timeout_budget,
        )
        wall = time.monotonic() - t0
        extras: dict[str, Any] = {}

        if t_result.hung:
            self._last_error = (
                f"snippet exceeded timeout_s={timeout_budget}; "
                "disconnect and re-launch the Mechanical session"
            )
            self._last_health = {
                **self.health(),
                "ok": False,
                "connected": False,
                "code": "mechanical.runtime.timeout_session_degraded",
                "message": "Mechanical snippet timed out",
            }
            result = {
                "ok": False,
                "label": label,
                "stdout": "",
                "stderr": "",
                "error": self._last_error,
                "result": None,
                "elapsed_s": round(wall, 4),
            }
            extras.update({
                "timeout_hit": True,
                "timeout_s": timeout_budget,
                "timeout_elapsed_s": wall,
            })
        elif t_result.exception is not None:
            exc = t_result.exception
            self._last_error = f"{type(exc).__name__}: {exc}"
            result = {
                "ok": False,
                "label": label,
                "stdout": "",
                "stderr": "",
                "error": "".join(
                    traceback.format_exception(type(exc), exc, exc.__traceback__)
                ),
                "result": None,
                "elapsed_s": round(wall, 4),
            }
        else:
            result = t_result.value

        guard_diagnostics: list[dict] = []
        if (
            result.get("ok")
            and self._looks_like_solve_attempt(code, label)
            and self._client is not None
        ):
            solve_state = self._solve_state()
            result["solve_state"] = solve_state
            incomplete = self._solve_incomplete_statuses(solve_state)
            if incomplete:
                status_text = ", ".join(incomplete)
                result["ok"] = False
                result["error"] = (
                    "Mechanical solve did not complete; "
                    f"solution_status={status_text}"
                )
                guard_diagnostics.append({
                    "severity": "error",
                    "source": "mechanical:solve",
                    "code": "mechanical.solve.not_completed",
                    "message": (
                        "Mechanical returned from the solve call, but at least "
                        "one analysis still requires solve or failed."
                    ),
                    "extra": {"statuses": incomplete},
                })

        ctx = InspectCtx(
            stdout=result.get("stdout", ""),
            stderr=result.get("error", "") or "",  # error string → stderr slot
            workdir=str(wd),
            wall_time_s=wall,
            exit_code=0 if result.get("ok") else 1,
            driver_name=self.name,
            session_ns={"_result": result.get("result")},
            workdir_before=before,
            extras=extras,
        )
        diags, arts = collect_diagnostics(self.probes, ctx)
        diags.extend(self._gui_coupling_diagnostics())
        result["diagnostics"] = [d.to_dict() for d in diags] + guard_diagnostics
        result["artifacts"] = [a.to_dict() for a in arts]
        if not result.get("ok") and result.get("error"):
            self._last_error = _safe_text(result.get("error"))
        self._last_run = result
        return result

    def _run_json_query(self, code: str) -> dict:
        if self._client is None:
            return {
                "ok": False,
                "connected": False,
                "code": "mechanical.session.disconnected",
                "message": "Mechanical session is not connected",
            }
        try:
            out = self._client.run_python_script(code)
            text = out if isinstance(out, str) else str(out or "")
            parsed = self.parse_output(text)
            return parsed or {"ok": False, "code": "mechanical.query.empty"}
        except Exception as exc:  # noqa: BLE001 - SDK exceptions vary
            return {
                "ok": False,
                "connected": self.is_connected,
                "code": "mechanical.query.failed",
                "message": _safe_text(f"{type(exc).__name__}: {exc}"),
            }

    def project_identity(self) -> dict:
        code = r'''
import json
def safe_count(fn):
    try:
        return fn()
    except:
        return None
analysis_types = []
result_files = []
solution_statuses = []
solution_result_counts = []
for a in Model.Analyses:
    try:
        analysis_types.append(str(a.AnalysisType))
    except:
        analysis_types.append("unknown")
    try:
        result_files.append(bool(a.ResultFileName))
    except:
        result_files.append(False)
    try:
        solution_statuses.append(str(a.Solution.Status))
    except:
        solution_statuses.append("unknown")
    try:
        solution_result_counts.append(len(a.Solution.Children))
    except:
        solution_result_counts.append(None)
body_count = safe_count(lambda: len(Model.Geometry.GetChildren(DataModelObjectCategory.Body, True)))
mesh_nodes = safe_count(lambda: int(Model.Mesh.Nodes))
mesh_elements = safe_count(lambda: int(Model.Mesh.Elements))
project_directory_known = safe_count(lambda: bool(ExtAPI.DataModel.Project.ProjectDirectory))
data = {
    "ok": True,
    "connected": True,
    "project_directory_known": bool(project_directory_known),
    "analysis_count": len(Model.Analyses),
    "analysis_types": analysis_types,
    "active_analysis_index": 0 if len(Model.Analyses) else None,
    "solution_statuses": solution_statuses,
    "solution_result_counts": solution_result_counts,
    "geometry_body_count": body_count,
    "mesh_nodes": mesh_nodes,
    "mesh_elements": mesh_elements,
    "result_file_available": any(result_files),
    "checkpoint_ready": bool(project_directory_known) and len(Model.Analyses) > 0
}
json.dumps(data)
'''
        return self._run_json_query(code)

    def model_summary(self) -> dict:
        code = r'''
import json
def safe_count(fn):
    try:
        return fn()
    except:
        return None
analyses = []
for i, a in enumerate(Model.Analyses):
    item = {"index": i}
    try:
        item["type"] = str(a.AnalysisType)
    except:
        item["type"] = "unknown"
    try:
        item["child_count"] = len(a.Children)
    except:
        item["child_count"] = None
    try:
        item["solution_child_count"] = len(a.Solution.Children)
    except:
        item["solution_child_count"] = None
    try:
        item["solution_status"] = str(a.Solution.Status)
    except:
        item["solution_status"] = "unknown"
    try:
        item["solution_result_count"] = len(a.Solution.Children)
    except:
        item["solution_result_count"] = None
    analyses.append(item)
data = {
    "ok": True,
    "connected": True,
    "analyses": analyses,
    "analysis_count": len(analyses),
    "named_selection_count": safe_count(lambda: len(Model.NamedSelections.Children)),
    "geometry_body_count": safe_count(lambda: len(Model.Geometry.GetChildren(DataModelObjectCategory.Body, True))),
    "mesh": {
        "nodes": safe_count(lambda: int(Model.Mesh.Nodes)),
        "elements": safe_count(lambda: int(Model.Mesh.Elements))
    }
}
json.dumps(data)
'''
        return self._run_json_query(code)

    def object_properties(self, target: str) -> dict:
        target = target.strip()
        if target == "mesh":
            return self._run_json_query(
                'import json\n'
                'json.dumps({"ok": True, "target": "mesh", '
                '"nodes": int(Model.Mesh.Nodes), "elements": int(Model.Mesh.Elements)})'
            )
        if target == "geometry":
            return self._run_json_query(
                'import json\n'
                'count = len(Model.Geometry.GetChildren(DataModelObjectCategory.Body, True))\n'
                'json.dumps({"ok": True, "target": "geometry", "body_count": count})'
            )
        match = re.match(r"^(analysis|solution):(\d+)$", target)
        if match:
            kind, index_text = match.groups()
            index = int(index_text)
            if kind == "analysis":
                code = (
                    "import json\n"
                    f"i = {index}\n"
                    "a = Model.Analyses[i]\n"
                    "json.dumps({\"ok\": True, \"target\": \"analysis:%d\" % i, "
                    "\"type\": str(a.AnalysisType), \"child_count\": len(a.Children)})"
                )
            else:
                code = (
                    "import json\n"
                    f"i = {index}\n"
                    "s = Model.Analyses[i].Solution\n"
                    "json.dumps({\"ok\": True, \"target\": \"solution:%d\" % i, "
                    "\"result_count\": len(s.Children)})"
                )
            return self._run_json_query(code)
        return {
            "ok": False,
            "code": "mechanical.object.unsupported_target",
            "message": (
                "supported targets are mesh, geometry, analysis:<index>, "
                "and solution:<index>"
            ),
            "target": _safe_text(target),
        }

    def capabilities(self, target: str = "active") -> dict:
        """Return live scripting capabilities for the current Mechanical state.

        The query intentionally exposes method surfaces and counts, not
        physics-specific decisions. Agents can use it to discover whether the
        live model supports a workflow before writing setup code.
        """
        target_json = json.dumps(target.strip() or "active")
        code = rf'''
import json

target = {target_json}

def method_names(obj, prefix=None):
    names = []
    try:
        raw = dir(obj)
    except:
        raw = []
    for name in raw:
        try:
            text = str(name)
        except:
            continue
        if prefix is None or text.startswith(prefix):
            names.append(text)
    names = sorted(set(names))
    return names

def safe_count(fn):
    try:
        return fn()
    except:
        return None

def selection_summary():
    out = []
    try:
        children = list(Model.NamedSelections.Children)
    except:
        return out
    for i, ns in enumerate(children):
        item = {{"index": i}}
        try:
            item["entity_count"] = int(ns.Location.Ids.Count)
        except:
            try:
                item["entity_count"] = len(list(ns.Location.Ids))
            except:
                item["entity_count"] = None
        try:
            item["location_type"] = str(type(ns.Location))
        except:
            item["location_type"] = None
        out.append(item)
    return out

analysis = None
solution = None
analysis_index = None
if target.startswith("analysis:"):
    try:
        analysis_index = int(target.split(":", 1)[1])
    except:
        analysis_index = None
elif len(Model.Analyses):
    analysis_index = 0

if analysis_index is not None:
    try:
        analysis = Model.Analyses[analysis_index]
        solution = analysis.Solution
    except:
        analysis = None
        solution = None

data = {{
    "ok": True,
    "connected": True,
    "target": target,
    "analysis_index": analysis_index,
    "analysis_count": len(Model.Analyses),
    "model_add_analysis_methods": [
        n for n in method_names(Model, "Add") if n.endswith("Analysis")
    ],
    "named_selections": selection_summary(),
    "geometry_body_count": safe_count(
        lambda: len(Model.Geometry.GetChildren(DataModelObjectCategory.Body, True))
    ),
    "mesh": {{
        "nodes": safe_count(lambda: int(Model.Mesh.Nodes)),
        "elements": safe_count(lambda: int(Model.Mesh.Elements)),
    }},
}}

if analysis is not None:
    add_methods = method_names(analysis, "Add")
    data["analysis"] = {{
        "type": safe_count(lambda: str(analysis.AnalysisType)),
        "child_count": safe_count(lambda: len(analysis.Children)),
        "add_methods": add_methods,
        "add_boundary_condition_methods": [
            n for n in add_methods
            if n not in ("AddComment", "AddFigure", "AddImage")
        ],
    }}
if solution is not None:
    data["solution"] = {{
        "status": safe_count(lambda: str(solution.Status)),
        "result_count": safe_count(lambda: len(solution.Children)),
        "add_result_methods": method_names(solution, "Add"),
    }}

json.dumps(data)
'''
        return self._run_json_query(code)

    def messages(self, limit: int = 20) -> dict:
        """Return recent Mechanical application messages for debugging."""
        code = rf'''
import json

def clean(value, limit=300):
    try:
        text = str(value)
    except:
        text = ""
    out = []
    for ch in text:
        o = ord(ch)
        out.append(ch if 32 <= o < 127 else "?")
    return "".join(out)[:limit]

items = []
try:
    messages = list(ExtAPI.Application.Messages)
except:
    messages = []
for m in messages[-{int(limit)}:]:
    items.append({{
        "severity": clean(getattr(m, "Severity", "")),
        "text": clean(getattr(m, "DisplayString", "")),
    }})
json.dumps({{"ok": True, "connected": True, "count": len(items), "messages": items}})
'''
        return self._run_json_query(code)

    def query(self, name: str) -> dict:
        """Session-level queries.

        ``session.summary`` is local metadata (cheap, no round-trip).
        ``mechanical.project_directory`` / ``mechanical.files`` /
        ``mechanical.product_info`` round-trip to the live session.
        """
        if name in {"health", "session.health"}:
            return self.health()
        if name in {"ui.modes", "session.ui_modes"}:
            return {
                "ok": True,
                "modes": {
                    "gui": "Visible Mechanical GUI coupled to PyMechanical SDK mutations.",
                    "no_gui": "Headless Mechanical session without screenshot confirmation.",
                    "batch": "Backward-compatible alias for no_gui.",
                },
                "aliases": {"gui": "gui", "visible": "gui", "no-gui": "no_gui", "no_gui": "no_gui", "batch": "batch"},
                "capabilities": _mechanical_ui_capabilities(self._ui_mode, self._batch),
            }
        if name in {"mechanical.project.identity", "project.identity"}:
            return self.project_identity()
        if name in {"mechanical.model.summary", "model.summary"}:
            return self.model_summary()
        if name.startswith("mechanical.object.properties:"):
            return self.object_properties(name.split(":", 1)[1])
        if name in {"mechanical.capabilities", "capabilities"}:
            return self.capabilities()
        if name.startswith("mechanical.capabilities:"):
            return self.capabilities(name.split(":", 1)[1])
        if name in {"mechanical.messages", "messages"}:
            return self.messages()
        if name == "session.summary":
            return {
                "session_id": self._session_id,
                "mode": self._mode,
                "ui_mode": self._ui_mode,
                "batch": self._batch,
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
                return {"product_version": self._product_version()}
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
            # Clear PID pin so the next launch starts in substring-fallback mode
            # until a fresh discovery succeeds.
            for p in self.probes:
                if hasattr(p, "target_pid"):
                    p.target_pid = None
            self._client = None
            self._session_id = None
            self._mode = None
            self._ui_mode = None
            self._batch = None
            self._run_count = 0
            self._version = None
            self._launched_at = None
            self._target_pid = None
            self._last_run = None
            self._last_error = None
            self._last_health = None

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
