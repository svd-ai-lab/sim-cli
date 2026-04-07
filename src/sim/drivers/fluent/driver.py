"""PyFluent driver — public API for sim."""
from __future__ import annotations

import ast
import os
import re
import uuid
from pathlib import Path
import sys

from sim.driver import ConnectionInfo, Diagnostic, LintResult
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
        """Detect installed Fluent version from environment variables."""
        # Check PYFLUENT_FLUENT_ROOT first (explicit override)
        fluent_root = os.environ.get("PYFLUENT_FLUENT_ROOT", "")
        if fluent_root:
            return _parse_fluent_version_from_path(fluent_root)

        # Scan AWP_ROOT* env vars (standard Ansys installation)
        awp_vars = sorted(
            ((k, v) for k, v in os.environ.items() if k.startswith("AWP_ROOT")),
            reverse=True,
        )
        if awp_vars:
            _, path = awp_vars[0]  # latest version
            return _parse_fluent_version_from_path(path)

        # Try common install paths
        for base in [
            Path("C:/Program Files/ANSYS Inc"),
            Path("/usr/ansys_inc"),
            Path("/ansys_inc"),
        ]:
            if base.is_dir():
                versions = sorted(base.glob("v*"), reverse=True)
                if versions:
                    return _parse_fluent_version_from_path(str(versions[0]))

        return None

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
