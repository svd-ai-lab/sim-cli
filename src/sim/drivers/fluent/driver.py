"""PyFluent driver — public API for sim."""
from __future__ import annotations

import ast
import os
import re
import uuid
from pathlib import Path
import sys

from sim.driver import ConnectionInfo, Diagnostic, LintResult, SolverInstall
from sim.drivers.fluent.queries import handle_query
from sim.drivers.fluent.runtime import PyFluentRuntime
from sim.inspect import (
    DomainExceptionMapProbe,
    GuiDialogProbe,
    InspectCtx,
    ProcessMetaProbe,
    PythonTracebackProbe,
    RuntimeTimeoutProbe,
    ScreenshotProbe,
    SdkAttributeProbe,
    StdoutJsonTailProbe,
    TextStreamRulesProbe,
    WorkdirDiffProbe,
    collect_diagnostics,
)
from sim.runner import run_subprocess


# Channel #2 — Fluent stderr rules (conservative).
_FLUENT_STDERR_RULES: list[dict] = [
    {"pattern": r"^\w+Error:", "severity": "error", "code": "generic.exception"},
    {"pattern": r"^\w+Exception:", "severity": "error", "code": "generic.exception"},
    {"pattern": r"RPC .* timeout", "severity": "error",
     "code": "fluent.rpc.timeout", "message_template": "Fluent RPC timeout"},
]

# Channel #6 — Fluent TUI echo (stdout). pyfluent's scheme_eval / solver.tui
# commands write to stdout via redirect_stdout. Watch for the canonical
# Fluent error/warning/done prefixes.
_FLUENT_TUI_STDOUT_RULES: list[dict] = [
    {"pattern": r"^Error:", "severity": "error",
     "code": "fluent.tui.error", "message_template": "TUI error: {match}"},
    {"pattern": r"^Warning:", "severity": "warning",
     "code": "fluent.tui.warning"},
    {"pattern": r"^Error Object:", "severity": "error",
     "code": "fluent.scheme.error_object"},
    {"pattern": r"Divergence detected", "severity": "error",
     "code": "fluent.solve.divergence"},
    {"pattern": r"floating point exception", "severity": "error",
     "code": "fluent.solve.fpe"},
    {"pattern": r"reversed flow in \d+ faces", "severity": "warning",
     "code": "fluent.solve.reversed_flow"},
]

# Channel #7 — Transcript file rules. Same kind of patterns as TUI but read
# out of the .trn file the session wrote to disk (if the user / test opened
# transcript logging via solver.file.start_transcript).
_FLUENT_TRN_RULES: list[dict] = _FLUENT_TUI_STDOUT_RULES  # same vocabulary

# Channel #4 — Default SDK attributes to probe on every run. These are the
# settings agents most often need to "reason about the current state" over.
_DEFAULT_FLUENT_SDK_ATTRS: list[str] = [
    "setup.models.viscous.model",
    "setup.models.energy.enabled",
]


def _read_transcript(ctx: InspectCtx) -> str:
    """Channel #7 text selector: read workdir/session.trn if it exists."""
    trn = Path(ctx.workdir) / "session.trn"
    try:
        return trn.read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, OSError):
        return ""


def _default_fluent_probes(enable_gui: bool = False) -> list:
    """Probes wired into every Fluent run() — all 9 channels.

    Baseline:
      #1 ProcessMetaProbe          — exit_code + wall_time
      #2 TextStreamRulesProbe(stderr) — generic Python exception lines
      #3 StdoutJsonTailProbe       — last JSON line / _result fallback
      #3+ PythonTracebackProbe     — structured traceback parsing
      #4 SdkAttributeProbe         — viscous model, energy enabled
      #5 DomainExceptionMapProbe   — python.* → fluent.* code upgrade
      #6 TextStreamRulesProbe(stdout:TUI) — TUI echo rule matching
      #7 TextStreamRulesProbe(log:session.trn) — transcript file, if opened
      #9 WorkdirDiffProbe          — new files → Artifacts

    GUI mode adds:
      #8a GuiDialogProbe           — cx/fluent/ansys windows, titles + dialogs
      #8b ScreenshotProbe          — per-window PNG crops (not desktop)

    Order matters: post-processors (#5) must run AFTER the probes whose
    output they consume (#3+). WorkdirDiff is last so new artifacts emitted
    by earlier probes (screenshots) are available on disk.
    """
    probes: list = [
        ProcessMetaProbe(),                                              # #1
        RuntimeTimeoutProbe(),                                           # #1+ (Phase 2: hung-snippet synthetic)
        TextStreamRulesProbe(                                            # #2
            source="stderr",
            text_selector=lambda ctx: ctx.stderr,
            rules=_FLUENT_STDERR_RULES,
        ),
        StdoutJsonTailProbe(),                                           # #3
        PythonTracebackProbe(),                                          # #3+
        SdkAttributeProbe(attr_paths=_DEFAULT_FLUENT_SDK_ATTRS),         # #4
        TextStreamRulesProbe(                                            # #6
            source="tui:stdout",
            text_selector=lambda ctx: ctx.stdout,
            rules=_FLUENT_TUI_STDOUT_RULES,
        ),
        TextStreamRulesProbe(                                            # #7
            source="log:session.trn",
            text_selector=_read_transcript,
            rules=_FLUENT_TRN_RULES,
        ),
        DomainExceptionMapProbe(),                                       # #5
    ]
    if enable_gui:
        probes.append(GuiDialogProbe(                                    # #8a
            process_name_substrings=("fluent", "ansys", "cx", "cortex")))
        probes.append(ScreenshotProbe(                                   # #8b
            filename_prefix="fluent_shot",
            process_name_substrings=("fluent", "ansys", "cx", "cortex")))
    probes.append(WorkdirDiffProbe())                                    # #9
    return probes


_VERSION_MAP = {
    "252": "2025 R2", "251": "2025 R1",
    "242": "2024 R2", "241": "2024 R1",
    "232": "2023 R2", "231": "2023 R1",
}


def _parse_fluent_version_from_path(path: str) -> str | None:
    """Extract Fluent version string from an install path like '.../v252'."""
    m = re.search(r"v(\d{3})", path)
    if not m:
        return None
    code = m.group(1)
    label = _VERSION_MAP.get(code, f"v{code}")
    return f"{label} (v{code})"


def _ansys_code_to_short(code: str) -> str:
    """Convert an Ansys release code (e.g. '252') to short form ('25.2')."""
    if len(code) == 3 and code.isdigit():
        return f"{code[:2]}.{code[2]}"
    return code


def _path_to_fluent_install(path: Path, source: str) -> "SolverInstall | None":
    """Validate that a candidate path actually contains a Fluent install."""
    if not path.is_dir():
        return None
    # Look for the v??? directory
    m = re.search(r"v(\d{3})", str(path))
    if not m:
        return None
    code = m.group(1)
    short = _ansys_code_to_short(code)

    # Check the install actually has a fluent binary (Linux & Windows)
    candidates = [
        path / "fluent" / "bin" / "fluent",                             # Linux
        path / "fluent" / "ntbin" / "win64" / "fluent.exe",              # Windows
    ]
    has_binary = any(p.exists() for p in candidates)
    if not has_binary:
        return None

    return SolverInstall(
        name="fluent",
        version=short,
        path=str(path),
        source=source,
        extra={"release_code": code, "release_label": _VERSION_MAP.get(code, f"v{code}")},
    )


def _scan_fluent_installs() -> list[SolverInstall]:
    """Find every Fluent installation on this host.

    Pure stdlib + this module's helpers. Safe to call when nothing is
    installed — returns [].
    """
    found: dict[str, SolverInstall] = {}  # path -> install (dedup by path)

    # 1) AWP_ROOT* env vars
    for k, v in os.environ.items():
        if not re.match(r"AWP_ROOT\d{3}$", k):
            continue
        if not v:
            continue
        install = _path_to_fluent_install(Path(v), source=f"env:{k}")
        if install and install.path not in found:
            found[install.path] = install

    # 2) Default install dirs (each platform)
    bases: list[Path] = [
        Path(r"C:\Program Files\ANSYS Inc"),
        Path("/usr/ansys_inc"),
        Path("/ansys_inc"),
        Path("/opt/ansys_inc"),
    ]
    for base in bases:
        if not base.is_dir():
            continue
        for vdir in sorted(base.glob("v???")):
            install = _path_to_fluent_install(vdir, source=f"default-path:{base}")
            if install and install.path not in found:
                found[install.path] = install

    # 3) Windows registry (best effort; never raises)
    try:
        import winreg  # type: ignore[import-not-found]
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                key = winreg.OpenKey(hive, r"SOFTWARE\Ansys, Inc.\Fluent")
            except OSError:
                continue
            try:
                i = 0
                while True:
                    try:
                        subname = winreg.EnumKey(key, i)
                    except OSError:
                        break
                    i += 1
                    # Subkey names look like "25.2.0"; values point at install dirs
                    try:
                        sub = winreg.OpenKey(key, subname)
                        install_dir, _ = winreg.QueryValueEx(sub, "InstallDir")
                        install = _path_to_fluent_install(
                            Path(install_dir).parent,  # InstallDir is .../fluent — go up
                            source="registry:HKLM" if hive == winreg.HKEY_LOCAL_MACHINE else "registry:HKCU",
                        )
                        if install and install.path not in found:
                            found[install.path] = install
                    except (OSError, FileNotFoundError):
                        continue
            finally:
                winreg.CloseKey(key)
    except ImportError:
        pass  # not on Windows

    # Stable order: highest version first
    return sorted(found.values(), key=lambda i: i.version, reverse=True)


class PyFluentDriver:
    """Sim driver for Ansys PyFluent (2024 R1+).

    DriverProtocol surface:
        name, detect, lint, connect, parse_output

    Extended PyFluent API:
        launch(mode, ip, port, password) -> dict   — start/connect a session
        run(code, label)                -> dict   — execute a snippet
        query(name)                     -> dict   — named query
    """

    # Process-name substrings that identify Fluent's own windows. Passed to
    # ``GuiController`` so agents don't accidentally grab unrelated apps.
    GUI_PROCESS_FILTER: tuple[str, ...] = ("fluent", "cx", "cortex", "fluentmeshing")

    def __init__(self, sim_dir: Path | None = None):
        self._runtime = PyFluentRuntime(sim_dir=sim_dir)
        # InspectProbe list — baseline 3. Phase 2 adds SDK-aware probes driven
        # by real failure fixtures. Mutable so future session-specific probes
        # can be appended post-launch (e.g. workdir watcher tied to the session's
        # working dir).
        self.probes = _default_fluent_probes()
        self._gui = None  # GuiController; set at launch() time when ui_mode=gui

    # ── DriverProtocol ───────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "fluent"

    @property
    def supports_session(self) -> bool:
        return True

    def detect(self, script: Path) -> bool:
        """Return True if the script imports ansys.fluent or pyfluent."""
        text = script.read_text(encoding="utf-8")
        return bool(
            re.search(
                r"^\s*(import ansys\.fluent|from ansys\.fluent\b"
                r"|import pyfluent|from pyfluent\b)",
                text,
                re.MULTILINE,
            )
        )

    def lint(self, script: Path) -> LintResult:
        """Syntax-only lint (thin adapter — no deep semantic checks)."""
        text = script.read_text(encoding="utf-8")
        try:
            ast.parse(text)
        except SyntaxError as e:
            return LintResult(
                ok=False,
                diagnostics=[
                    Diagnostic(level="error", message=f"Syntax error: {e}", line=e.lineno)
                ],
            )
        return LintResult(ok=True, diagnostics=[])

    def connect(self) -> ConnectionInfo:
        """DriverProtocol connect: check ansys-fluent-core availability."""
        try:
            import ansys.fluent.core as pyfluent  # noqa: PLC0415

            version = getattr(pyfluent, "__version__", "unknown")
            solver_version = self._detect_fluent_version()
            msg = f"ansys-fluent-core {version} available"
            if solver_version:
                msg += f", Fluent {solver_version}"
            return ConnectionInfo(
                solver="fluent",
                version=version,
                status="ok",
                message=msg,
                solver_version=solver_version,
            )
        except ImportError:
            return ConnectionInfo(
                solver="fluent",
                version=None,
                status="not_installed",
                message="ansys-fluent-core is not installed",
            )

    @staticmethod
    def _detect_fluent_version() -> str | None:
        """Detect ONE installed Fluent version (legacy single-result helper).

        Kept for backward compatibility with the existing connect() output.
        New code should call detect_installed() and handle the full list.
        """
        installs = _scan_fluent_installs()
        if not installs:
            return None
        # Highest version first (sorted by _scan_fluent_installs)
        top = installs[0]
        code = top.extra.get("release_code", top.version.replace(".", ""))
        label = top.extra.get("release_label", top.version)
        return f"{label} (v{code})"

    def detect_installed(self) -> list[SolverInstall]:
        """Enumerate all Fluent installations visible on this host.

        Strategy (in priority order; deduplicated by install path):
          1. AWP_ROOT* environment variables (the canonical Ansys signal)
          2. Default install dirs under C:\\Program Files\\ANSYS Inc\\v???
             and /usr/ansys_inc/v??? (Linux)
          3. Windows registry HKLM\\SOFTWARE\\Ansys, Inc.\\Fluent (best effort)

        Pure Python. Does NOT import ansys.fluent.core. Returns [] if nothing
        is found (e.g. on a Mac without any Fluent install).
        """
        return _scan_fluent_installs()

    def parse_output(self, stdout: str) -> dict:
        """Extract structured results from a pyfluent script's stdout.

        Convention: the script prints a JSON object as the last JSON line
        (e.g. ``print(json.dumps({...}))``). Scans stdout in reverse and
        returns the first line that parses as a JSON object.
        """
        import json  # noqa: PLC0415

        for line in reversed(stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        return {}

    def run_file(self, script: Path):
        """Execute a one-shot PyFluent Python script."""
        return run_subprocess(
            [sys.executable, str(script)],
            script=script,
            solver=self.name,
        )

    # ── Extended PyFluent API ────────────────────────────────────────────────────

    def launch(
        self,
        mode: str = "meshing",
        ip: str | None = None,
        port: int | None = None,
        password: str | None = None,
        ui_mode: str = "gui",
        processors: int | None = None,
        **kwargs,
    ) -> dict:
        """
        Launch or connect to a Fluent session. Returns a structured dict.

        Args:
            mode: "meshing" or "solver" for local launch.
            ip/port/password: If provided, connect to an existing session.
                              v0 detects mode as "solver" for remote connections.
            ui_mode: "gui" (default) opens the Fluent GUI for visual confirmation;
                     "no_gui" for headless runs.

        Returns:
            {"ok": True, "session_id": "...", "mode": "...", "source": "..."}
        """
        try:
            import ansys.fluent.core as pyfluent  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError(
                "ansys-fluent-core is not installed. "
                "Run: pip install ansys-fluent-core"
            ) from exc

        # Ensure pyfluent can locate Fluent 2024 R1 (v241).
        # pyfluent >=0.38.0 dropped v241 from FluentVersion enum. The
        # PYFLUENT_FLUENT_ROOT env var was a valid workaround pre-0.38 but
        # the post-connect scheme_eval.version check still trips on
        # Fluent 2024 R1 (observed on 0.38.1). Phase 1 STATUS §3.1 documents
        # this. pyproject now pins >=0.37,<0.39 so 0.37.x (which supports
        # v241 end-to-end) is the default. We still set the env var here
        # for 0.37.x's own launcher check.
        if not os.environ.get("PYFLUENT_FLUENT_ROOT"):
            awp241 = os.environ.get("AWP_ROOT241")
            if awp241:
                os.environ["PYFLUENT_FLUENT_ROOT"] = str(
                    Path(awp241) / "fluent"
                )

        if ip is not None and port is not None:
            session = pyfluent.connect_to_fluent(
                ip=ip, port=port, password=password or ""
            )
            source = "connection"
            mode = "solver"
        else:
            # Ensure Fluent binds to 127.0.0.1 (via REMOTING_SERVER_ADDRESS)
            # so pyfluent's localhost check passes when reading back the
            # server-info file.  Without this, Fluent may advertise its
            # LAN IP and pyfluent raises "remote host" error on 0.37.2.
            if not pyfluent.config.launch_fluent_ip:
                pyfluent.config.launch_fluent_ip = "127.0.0.1"

            launch_kwargs = {"ui_mode": ui_mode}
            if mode == "meshing":
                launch_kwargs["mode"] = "meshing"
            if processors is not None:
                launch_kwargs["processor_count"] = processors
            session = pyfluent.launch_fluent(**launch_kwargs)
            source = "launch"

        session_id = str(uuid.uuid4())
        info = self._runtime.register_session(session_id, mode, source, session)
        # Auto-enable GUI probes when the session is actually running with a
        # visible GUI. Headless (no_gui/hidden_gui) sessions don't benefit —
        # the screenshot would be blank and the dialog enum would find nothing
        # Fluent-owned. Users can still opt in by setting driver.probes =
        # _default_fluent_probes(enable_gui=True) explicitly.
        gui_mode = isinstance(ui_mode, str) and ui_mode.lower() == "gui"
        if gui_mode:
            self.probes = _default_fluent_probes(enable_gui=True)
        # Phase 3: inject a GuiController into the session namespace so
        # agents can click / type / dismiss Fluent dialogs via `sim exec`.
        # Kept on the driver so every exec snippet reuses the same object.
        from sim.gui import GuiController  # noqa: PLC0415
        self._gui = GuiController(
            process_name_substrings=self.GUI_PROCESS_FILTER,
            workdir=str(self._runtime._sim_dir),
        ) if gui_mode else None
        return info.to_dict()

    def run(
        self, code: str, label: str = "pyfluent-snippet",
        timeout_s: float | None = None,
    ) -> dict:
        """
        Execute a PyFluent snippet in the active session.

        The snippet runs with session/solver/meshing/_result injected.
        Assign to _result to return structured data.

        `timeout_s` (Phase 2): per-snippet deadline. Default 300s via
        `sim._timeout.DEFAULT_TIMEOUT_S`. Pass explicit value to override.
        On timeout → ok=False, error string names the timeout, and the
        probe layer emits `sim.runtime.snippet_timeout`.

        Returns:
            {run_id, ok, label, stdout, stderr, error, result,
             diagnostics[], artifacts[]}
        """
        # Snapshot workdir BEFORE the snippet runs so WorkdirDiffProbe can
        # later emit only newly-introduced files as Artifacts. The snapshot
        # is a list of relative paths.
        workdir_path = Path(self._runtime._sim_dir)
        try:
            workdir_path.mkdir(parents=True, exist_ok=True)
            before = sorted(
                str(p.relative_to(workdir_path)).replace("\\", "/")
                for p in workdir_path.rglob("*") if p.is_file()
            )
        except Exception:
            before = []

        extra_ns: dict = {}
        if self._gui is not None:
            extra_ns["gui"] = self._gui
        record = self._runtime.exec_snippet(
            code=code, label=label, timeout_s=timeout_s,
            extra_namespace=extra_ns or None,
        )
        out = record.to_run_result()

        # Build the inspect context from what the runtime captured. ok=False
        # gets mapped to exit_code=1 so ProcessMetaProbe treats it as failure.
        session_info = self._runtime.get_active_session()
        session_ns: dict = {}
        if session_info is not None:
            session_ns["session"] = session_info.session
            session_ns["solver_kind"] = session_info.mode
        if record.error:
            session_ns["_session_error"] = record.error
        if record.result is not None:
            session_ns["_result"] = record.result

        wall = max(0.0, record.ended_at - record.started_at)
        extras: dict = {}
        # Plumb timeout state for RuntimeTimeoutProbe
        err = record.error or ""
        if "exceeded timeout_s" in err or "hung in Fluent RPC" in err:
            from sim._timeout import DEFAULT_TIMEOUT_S  # noqa: PLC0415
            extras["timeout_hit"] = True
            extras["timeout_s"] = (
                timeout_s if timeout_s is not None else DEFAULT_TIMEOUT_S
            )
            extras["timeout_elapsed_s"] = wall

        ctx = InspectCtx(
            stdout=record.stdout or "",
            stderr=record.stderr or "",
            workdir=str(workdir_path),
            wall_time_s=wall,
            exit_code=0 if record.ok else 1,
            driver_name=self.name,
            session_ns=session_ns,
            workdir_before=before,
            extras=extras,
        )
        diags, arts = collect_diagnostics(self.probes, ctx)
        out["diagnostics"] = [d.to_dict() for d in diags]
        out["artifacts"] = [a.to_dict() for a in arts]
        return out

    def disconnect(self) -> dict:
        """Tear down the active Fluent session."""
        session_info = self._runtime.get_active_session()
        if session_info is not None:
            try:
                session_info.session.exit()
            except Exception:
                pass
            self._runtime._active_id = None
        self._gui = None
        return {"ok": True, "disconnected": True}

    def query(self, name: str) -> dict:
        """
        Run a named query against the active session.

        Supported names: session.summary, workflow.summary, last.result, field.catalog
        """
        return handle_query(name, self._runtime)
