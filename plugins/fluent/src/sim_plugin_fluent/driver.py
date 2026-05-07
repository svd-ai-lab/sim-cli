"""PyFluent driver — public API for sim."""
from __future__ import annotations

import ast
import inspect
import os
import re
import shutil
import uuid
from pathlib import Path
import sys

from sim.driver import ConnectionInfo, Diagnostic, LintResult, SolverInstall
from sim.inspect import (
    GuiDialogProbe,
    InspectCtx,
    ScreenshotProbe,
    SdkAttributeProbe,
    collect_diagnostics,
    generic_probes,
)
from sim.runner import run_subprocess

from .artifacts import classify_fluent_artifact
from .queries import handle_query
from .runtime import PyFluentRuntime


# Default SDK attributes to probe on every run. These are observation —
# the agent reads the raw value, not a pre-judged status. Reading raw
# attributes is "extract facts", which is driver-layer work.
_DEFAULT_FLUENT_SDK_ATTRS: list[str] = [
    "setup.models.viscous.model",
    "setup.models.energy.enabled",
]


def _default_fluent_probes(enable_gui: bool = False) -> list:
    """Fluent probe list — generic_probes() + SDK readers + optional GUI.

    No driver-layer semantic assertions: "what counts as an error" is the
    agent's job, not the driver's. Probes here only extract facts.
    SdkAttributeProbe reads raw pyfluent SDK attribute values (observation,
    not judgement) — the agent decides whether the values are healthy.
    """
    probes: list = list(generic_probes())
    probes.append(SdkAttributeProbe(attr_paths=_DEFAULT_FLUENT_SDK_ATTRS))
    if enable_gui:
        probes.append(GuiDialogProbe(
            process_name_substrings=("fluent", "ansys", "cx", "cortex")))
        probes.append(ScreenshotProbe(
            filename_prefix="fluent_shot",
            process_name_substrings=("fluent", "ansys", "cx", "cortex")))
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


def _normalize_launch_options(
    *,
    mode: str,
    ui_mode: str,
    dimension: int | None,
    precision: str,
    processors: int | None,
    processor_count: int | None,
    cwd: str | os.PathLike[str] | None,
) -> dict:
    """Validate and normalize launch options before passing them to PyFluent."""
    if mode not in {"meshing", "solver"}:
        raise ValueError("mode must be 'meshing' or 'solver'")
    if dimension is not None and dimension not in {2, 3}:
        raise ValueError("dimension must be 2, 3, or None")
    if precision not in {"single", "double"}:
        raise ValueError("precision must be 'single' or 'double'")
    if processors is not None and processor_count is not None and processors != processor_count:
        raise ValueError("processors and processor_count disagree")
    normalized_processor_count = processor_count if processor_count is not None else processors
    if normalized_processor_count is not None and normalized_processor_count < 1:
        raise ValueError("processor_count must be >= 1")
    normalized_cwd = str(Path(cwd).resolve()) if cwd is not None else None
    return {
        "mode": mode,
        "ui_mode": ui_mode,
        "dimension": dimension,
        "precision": precision,
        "processor_count": normalized_processor_count,
        "cwd": normalized_cwd,
    }


def _call_with_supported_kwargs(fn, kwargs: dict):
    """Call a PyFluent function while tolerating SDK keyword drift."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return fn(**kwargs)

    params = sig.parameters
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return fn(**kwargs)

    filtered = {
        name: value
        for name, value in kwargs.items()
        if name in params
    }
    return fn(**filtered)


def _candidate_install_roots(path: Path) -> list[Path]:
    roots = [path]
    if path.name.lower() == "fluent":
        roots.append(path.parent)
    for parent in path.parents:
        if re.fullmatch(r"v\d{3}", parent.name, flags=re.IGNORECASE):
            roots.append(parent)
            break
    return roots


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

    def add_candidate(path: Path, source: str) -> None:
        for root in _candidate_install_roots(path):
            install = _path_to_fluent_install(root, source=source)
            if install and install.path not in found:
                found[install.path] = install

    # 1) AWP_ROOT* env vars
    for k, v in os.environ.items():
        if not re.match(r"AWP_ROOT\d{3}$", k):
            continue
        if not v:
            continue
        add_candidate(Path(v), source=f"env:{k}")

    # 2) Explicit Fluent root hints.
    for k in ("SIM_FLUENT_ROOT", "FLUENT_ROOT", "PYFLUENT_FLUENT_ROOT"):
        v = os.environ.get(k)
        if v:
            add_candidate(Path(v), source=f"env:{k}")

    # 3) Fluent on PATH.
    fluent_binary = shutil.which("fluent")
    if fluent_binary:
        add_candidate(Path(fluent_binary), source="path:fluent")

    # 4) Default install dirs (each platform)
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
            add_candidate(vdir, source=f"default-path:{base}")

    # 5) Windows registry (best effort; never raises)
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
                        add_candidate(
                            Path(install_dir).parent,
                            source="registry:HKLM" if hive == winreg.HKEY_LOCAL_MACHINE else "registry:HKCU",
                        )
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
        self._pyfluent_version: str | None = None

    # ── DriverProtocol ───────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "fluent"

    @property
    def supports_session(self) -> bool:
        return True

    def detect(self, script: Path) -> bool:
        """Return True if the script imports ansys.fluent or pyfluent."""
        try:
            text = script.read_text(encoding="utf-8")
        except OSError:
            return False
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
        try:
            text = script.read_text(encoding="utf-8")
        except OSError as e:
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(level="error", message=f"Cannot read file: {e}")],
            )
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
        processor_count: int | None = None,
        dimension: int | None = None,
        precision: str = "double",
        cwd: str | os.PathLike[str] | None = None,
        workspace: str | os.PathLike[str] | None = None,
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
            processors/processor_count: Number of Fluent compute processes.
            dimension: 2 or 3 for local solver launches.
            precision: "single" or "double".
            cwd/workspace: Working directory for Fluent and run artifact discovery.

        Returns:
            {"ok": True, "session_id": "...", "mode": "...", "source": "..."}
        """
        if kwargs:
            names = ", ".join(sorted(kwargs))
            raise ValueError(f"unknown Fluent launch option(s): {names}")

        try:
            import ansys.fluent.core as pyfluent  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError(
                "ansys-fluent-core is not installed. "
                "Run: pip install ansys-fluent-core"
            ) from exc
        self._pyfluent_version = getattr(pyfluent, "__version__", None)

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

        launch_options = _normalize_launch_options(
            mode=mode,
            ui_mode=ui_mode,
            dimension=dimension,
            precision=precision,
            processors=processors,
            processor_count=processor_count,
            cwd=cwd if cwd is not None else workspace,
        )

        if ip is not None and port is not None:
            session = _call_with_supported_kwargs(
                pyfluent.connect_to_fluent,
                {"ip": ip, "port": port, "password": password or ""},
            )
            source = "connection"
            mode = "solver"
            launch_options = {
                **launch_options,
                "mode": mode,
                "ip": ip,
                "port": port,
                "cwd": launch_options.get("cwd"),
            }
        else:
            # Ensure Fluent binds to 127.0.0.1 (via REMOTING_SERVER_ADDRESS)
            # so pyfluent's localhost check passes when reading back the
            # server-info file.  Without this, Fluent may advertise its
            # LAN IP and pyfluent raises "remote host" error on 0.37.2.
            if not pyfluent.config.launch_fluent_ip:
                pyfluent.config.launch_fluent_ip = "127.0.0.1"

            launch_kwargs = {
                "ui_mode": ui_mode,
                "precision": precision,
            }
            if mode == "meshing":
                launch_kwargs["mode"] = "meshing"
            else:
                launch_kwargs["mode"] = "solver"
            if dimension is not None:
                launch_kwargs["dimension"] = dimension
            if launch_options["processor_count"] is not None:
                launch_kwargs["processor_count"] = launch_options["processor_count"]
            if launch_options["cwd"] is not None:
                launch_kwargs["cwd"] = launch_options["cwd"]
            session = _call_with_supported_kwargs(pyfluent.launch_fluent, launch_kwargs)
            source = "launch"

        session_id = str(uuid.uuid4())
        info = self._runtime.register_session(
            session_id,
            mode,
            source,
            session,
            launch_options=launch_options,
        )
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
            workdir=str(self._runtime.sim_dir),
        ) if gui_mode else None
        out = info.to_dict()
        out["health"] = self.health()
        return out

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
        session_info = self._runtime.get_active_session()
        launch_options = session_info.launch_options if session_info is not None else {}
        workdir_path = Path(launch_options.get("cwd") or self._runtime.sim_dir)
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
        for art in arts:
            art.role = classify_fluent_artifact(art.path, art.role)
        out["diagnostics"] = [d.to_dict() for d in diags]
        out["artifacts"] = [a.to_dict() for a in arts]
        return out

    def health(self) -> dict:
        """Return a lightweight health summary for the active Fluent session."""
        return handle_query("session.health", self._runtime, driver=self)

    def disconnect(self) -> dict:
        """Tear down the active Fluent session."""
        session_info = self._runtime.get_active_session()
        if session_info is not None:
            try:
                session_info.session.exit()
            except Exception:
                pass
            self._runtime.clear_active()
        self._gui = None
        self.probes = _default_fluent_probes()
        return {"ok": True, "disconnected": True}

    def query(self, name: str) -> dict:
        """
        Run a named query against the active session.

        Supported names include session.summary, session.health,
        session.versions, workflow.summary, last.result, field.catalog,
        and Fluent-specific fluent.* summaries.
        """
        return handle_query(name, self._runtime, driver=self)
