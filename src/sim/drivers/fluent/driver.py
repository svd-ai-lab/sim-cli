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
from sim.runner import run_subprocess


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

    def __init__(self, sim_dir: Path | None = None):
        self._runtime = PyFluentRuntime(sim_dir=sim_dir)

    # ── DriverProtocol ───────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "fluent"

    def detect(self, script: Path) -> bool:
        """Return True if the script imports ansys.fluent or pyfluent."""
        text = script.read_text()
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
        text = script.read_text()
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
        # pyfluent >=0.38.0 dropped v241 from its FluentVersion enum, but it
        # still honours the PYFLUENT_FLUENT_ROOT env var which bypasses the
        # version check entirely.  If the user has AWP_ROOT241 set (standard
        # Fluent 2024 R1 installation) and hasn't already pointed
        # PYFLUENT_FLUENT_ROOT elsewhere, we set it automatically.
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

            if mode == "meshing":
                session = pyfluent.launch_fluent(
                    mode="meshing",
                    ui_mode=ui_mode,
                )
                source = "launch"
            else:
                session = pyfluent.launch_fluent(ui_mode=ui_mode)
                source = "launch"

        session_id = str(uuid.uuid4())
        info = self._runtime.register_session(session_id, mode, source, session)
        return info.to_dict()

    def run(self, code: str, label: str = "pyfluent-snippet") -> dict:
        """
        Execute a PyFluent snippet in the active session.

        The snippet runs with session/solver/meshing/_result injected.
        Assign to _result to return structured data.

        Returns:
            {"run_id", "ok", "label", "stdout", "stderr", "error", "result"}
        """
        record = self._runtime.exec_snippet(code=code, label=label)
        return record.to_run_result()

    def query(self, name: str) -> dict:
        """
        Run a named query against the active session.

        Supported names: session.summary, workflow.summary, last.result, field.catalog
        """
        return handle_query(name, self._runtime)
