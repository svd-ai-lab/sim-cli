"""COMSOL Multiphysics driver for sim.

Architecture (M1):
- detect_installed() scans the host for COMSOL installs
- compatibility.yaml maps detected versions → profile envs with `mph` pinned
- The actual COMSOL session lives in a runner subprocess
  (sim._runners.comsol.mph_runner) inside the profile env

This module is therefore SDK-free: it does NOT import `mph` or `jpype`
at module load time, so `sim check comsol` works on a host without any
Python COMSOL bindings installed.
"""
from __future__ import annotations

import ast
import glob
import io
import json
import os
import re
import shutil
import sys
import time
import traceback
import uuid
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Callable, TextIO

from sim.driver import ConnectionInfo, Diagnostic, LintResult, SolverInstall
from sim.inspect import (
    Diagnostic as RuntimeDiagnostic,
    GuiDialogProbe,
    InspectCtx,
    ScreenshotProbe,
    SdkAttributeProbe,
    collect_diagnostics,
    generic_probes,
)
from sim.runner import run_subprocess


class ComsolLifecycleError(RuntimeError):
    """COMSOL launch/session failure with machine-readable diagnostics."""

    def __init__(self, message: str, diagnostics: dict):
        super().__init__(message)
        self.diagnostics = diagnostics

    def __str__(self) -> str:
        bits = [super().__str__()]
        if code := self.diagnostics.get("code"):
            bits.append(f"code={code}")
        if port := self.diagnostics.get("port"):
            bits.append(f"port={port}")
        if pid := self.diagnostics.get("server_pid"):
            bits.append(f"server_pid={pid}")
        rc = self.diagnostics.get("server_returncode")
        if rc is not None:
            bits.append(f"server_returncode={rc}")
        if log_path := self.diagnostics.get("server_log_path"):
            bits.append(f"server_log_path={log_path}")
        if log_tail := self.diagnostics.get("server_log_tail"):
            bits.append(f"server_log_tail={log_tail!r}")
        return " | ".join(bits)


_COMSOL_UI_MODE_ALIASES = {
    "": "no_gui",
    "no_gui": "no_gui",
    "no-gui": "no_gui",
    "nogui": "no_gui",
    "gui": "server-graphics",
    "visible": "server-graphics",
    "graphics": "server-graphics",
    "server_graphics": "server-graphics",
    "server-graphics": "server-graphics",
    "shared_desktop": "shared-desktop",
    "shared-desktop": "shared-desktop",
    "desktop": "server-graphics",
    "desktop-inspection": "server-graphics",
}

_COMSOL_VISUAL_MODE_ALIASES = {
    "": None,
    "default": None,
    "auto": None,
    "server_graphics": "server-graphics",
    "server-graphics": "server-graphics",
    "graphics": "server-graphics",
    "shared": "shared-desktop",
    "shared_desktop": "shared-desktop",
    "shared-desktop": "shared-desktop",
    "desktop": "shared-desktop",
}

_COMSOL_UI_MODE_NOTES = {
    "gui": (
        "ui_mode='gui' is a legacy alias for server-graphics: COMSOL "
        "server-side plot windows may appear, but full Model Builder is "
        "not attached to the live session."
    ),
    "visible": "ui_mode='visible' is treated as server-graphics.",
    "graphics": "ui_mode='graphics' is treated as server-graphics.",
    "server_graphics": "ui_mode='server_graphics' is treated as server-graphics.",
    "desktop": (
        "ui_mode='desktop' is not a live shared Desktop mode yet. The "
        "current launch uses server-graphics; save the .mph artifact and "
        "open it in COMSOL Desktop for inspection."
    ),
    "desktop-inspection": (
        "desktop-inspection is an artifact workflow, not a live session "
        "mode. The current launch uses server-graphics; open the saved .mph "
        "artifact in COMSOL Desktop for Model Builder inspection."
    ),
    "shared_desktop": (
        "ui_mode='shared_desktop' launches shared-desktop mode; prefer "
        "--driver-option visual_mode=shared-desktop from sim-cli."
    ),
    "shared-desktop": (
        "ui_mode='shared-desktop' launches shared-desktop mode; prefer "
        "--driver-option visual_mode=shared-desktop from sim-cli."
    ),
}


# ── Channel #4 — default SDK attribute readers (COMSOL / MPh Model Java API) ──
def _default_comsol_readers() -> list[tuple[str, object]]:
    """Each reader is (label, callable(session) -> value). The session is
    the MPh Model object. Readers call Java-API methods, NOT getattr chains.

    Readers are wrapped so a missing/unavailable Java sub-object emits a
    warning (via SdkAttributeProbe's exception handler) instead of crashing.
    """
    return [
        ("model.physics.count",
         lambda m: len(list(m.physics().tags())) if hasattr(m, "physics") else None),
        ("model.study.count",
         lambda m: len(list(m.study().tags())) if hasattr(m, "study") else None),
        ("model.material.count",
         lambda m: len(list(m.material().tags())) if hasattr(m, "material") else None),
        ("model.hist",
         lambda m: str(m.hist())[:200] if hasattr(m, "hist") else None),
    ]


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _default_comsol_probes(enable_gui: bool = False) -> list:
    """COMSOL's probe list — generic_probes() + SDK readers + MPH file
    probe + optional GUI.

    No driver-layer semantic assertions: "what counts as an error" is the
    agent's job, not the driver's. Probes here only extract facts.
    SdkAttributeProbe reads raw Java-API attribute values (observation,
    not judgement) — the agent decides whether the values are healthy.
    MphFileProbe describes any new .mph file that the run produced
    via the stdlib ZIP reader (no JVM round-trip).
    """
    from .lib.mph_inspect import MphFileProbe  # noqa: PLC0415

    probes: list = list(generic_probes())
    probes.append(SdkAttributeProbe(
        readers=_default_comsol_readers(),
        source_prefix="sdk:attr",
        code_prefix="comsol.sdk.attr",
    ))
    probes.append(MphFileProbe(only_new=True))
    if enable_gui:
        probes.append(GuiDialogProbe(
            process_name_substrings=("comsol", "comsolui", "mphserver"),
            code_prefix="comsol.gui",
        ))
        probes.append(ScreenshotProbe(
            filename_prefix="comsol_shot",
            process_name_substrings=("comsol", "comsolui", "mphserver"),
        ))
    return probes


# ─── extension points (open for additions, closed for modifications) ──────
#
# Both detection layers — *where* to look for COMSOL installs and *how* to
# read a version string out of one — are strategy chains. To add support
# for a new layout (e.g. COMSOL 7.0 ships with version.json instead of
# readme.txt, or a Linux package manager drops files at /usr/share/comsol*)
# you append one function to the relevant list. The scanner walks the
# chain in order; first hit wins.
#
# Do NOT modify existing functions for new layouts — add a new one. The
# whole point of this design is that the existing path stays validated.

# ─── version probes ───────────────────────────────────────────────────────


def _version_from_readme(install_dir: Path) -> str | None:
    """COMSOL 5.x – 6.x: readme.txt first line = 'COMSOL X.Y.Z.BBB README'."""
    readme = install_dir / "readme.txt"
    if not readme.is_file():
        return None
    try:
        first = readme.read_text(encoding="utf-8", errors="replace").splitlines()[:1]
    except OSError:
        return None
    if not first:
        return None
    m = re.search(r"COMSOL\s+(\d+\.\d+(?:\.\d+(?:\.\d+)?)?)", first[0])
    return m.group(1) if m else None


def _version_from_about_txt(install_dir: Path) -> str | None:
    """COMSOL 6.x: about.txt first line = 'SOFTWARE COMPONENTS IN COMSOL X.Y'.

    Used as a fallback when readme.txt is missing (some custom installers
    only ship about.txt).
    """
    about = install_dir / "about.txt"
    if not about.is_file():
        return None
    try:
        first = about.read_text(encoding="utf-8", errors="replace").splitlines()[:1]
    except OSError:
        return None
    if not first:
        return None
    m = re.search(r"COMSOL\s+(\d+\.\d+(?:\.\d+)?)", first[0])
    return m.group(1) if m else None


def _version_from_dir_name(install_dir: Path) -> str | None:
    """Last-resort: parse the install dir name itself.

    Examples this catches:
        comsol62/multiphysics  → 6.2
        COMSOL61/Multiphysics  → 6.1
        comsol-7.0             → 7.0
    """
    for part in (install_dir.name, install_dir.parent.name):
        m = re.search(r"comsol[-_]?(\d)(\d)", part, re.IGNORECASE)
        if m:
            return f"{m.group(1)}.{m.group(2)}"
        m = re.search(r"comsol[-_](\d+\.\d+)", part, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


_VERSION_PROBES: list[Callable[[Path], str | None]] = [
    _version_from_readme,
    _version_from_about_txt,
    _version_from_dir_name,
]
"""Strategy chain. APPEND new probes for new COMSOL layouts; do not edit."""


def _read_install_version(install_dir: Path) -> str | None:
    for probe in _VERSION_PROBES:
        try:
            v = probe(install_dir)
        except Exception:
            v = None
        if v:
            return v
    return None


# ─── install-dir finders ──────────────────────────────────────────────────


def _comsol_binary_paths(install_dir: Path) -> list[Path]:
    """Where the comsol launcher binary is expected to live (per platform)."""
    return [
        install_dir / "bin" / "win64" / "comsol.exe",
        install_dir / "bin" / "win64" / "comsolmphserver.exe",
        install_dir / "bin" / "comsol",
        install_dir / "bin" / "glnxa64" / "comsol",
        install_dir / "bin" / "maci64" / "comsol",
        install_dir / "bin" / "macarm64" / "comsol",
    ]


def _has_comsol_binary(install_dir: Path) -> bool:
    return any(p.exists() for p in _comsol_binary_paths(install_dir))


def _candidates_from_env() -> list[tuple[Path, str]]:
    """COMSOL_ROOT env var — the canonical user-set signal."""
    out: list[tuple[Path, str]] = []
    root = os.environ.get("COMSOL_ROOT")
    if root:
        out.append((Path(root), "env:COMSOL_ROOT"))
    return out


def _candidates_from_windows_defaults() -> list[tuple[Path, str]]:
    """Windows: C:\\Program Files\\COMSOL\\COMSOL{XX}\\Multiphysics\\ etc.

    Probes every common drive letter (C:/D:/E:) under both
    ``Program Files`` and ``Program Files (x86)`` — the COMSOL installer
    lets the user pick a different drive on multi-disk setups.
    """
    bases: list[Path] = []
    for drive in ("C:", "D:", "E:"):
        bases.extend([
            Path(rf"{drive}\Program Files\COMSOL"),
            Path(rf"{drive}\Program Files (x86)\COMSOL"),
            Path(rf"{drive}\Program Files (x86)\COMSOL64\Multiphysics"),
        ])
    out: list[tuple[Path, str]] = []
    for base in bases:
        if not base.is_dir():
            continue
        # Direct hit — base IS a Multiphysics dir
        if _has_comsol_binary(base):
            out.append((base, f"default-path:{base}"))
            continue
        # Otherwise scan one level: COMSOL{XX}/Multiphysics
        for child in sorted(base.iterdir()):
            mp = child / "Multiphysics"
            if mp.is_dir():
                out.append((mp, f"default-path:{base}"))
            elif _has_comsol_binary(child):
                out.append((child, f"default-path:{base}"))
    return out


def _candidates_from_linux_defaults() -> list[tuple[Path, str]]:
    """Linux: /usr/local/comsol*/multiphysics, /opt/comsol*/multiphysics."""
    bases = [Path("/usr/local"), Path("/opt"), Path("/usr/lib")]
    out: list[tuple[Path, str]] = []
    for base in bases:
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if "comsol" not in child.name.lower():
                continue
            mp = child / "multiphysics"
            if mp.is_dir():
                out.append((mp, f"default-path:{base}"))
            elif _has_comsol_binary(child):
                out.append((child, f"default-path:{base}"))
    return out


def _candidates_from_macos_defaults() -> list[tuple[Path, str]]:
    """macOS: /Applications/COMSOL{NN}/Multiphysics/ — the layout used
    by the official COMSOL installer. Same naming convention as the
    `sim-skills/comsol/doc-search` skill expects."""
    base = Path("/Applications")
    out: list[tuple[Path, str]] = []
    if not base.is_dir():
        return out
    for child in sorted(base.iterdir()):
        if "comsol" not in child.name.lower():
            continue
        mp = child / "Multiphysics"
        if mp.is_dir():
            out.append((mp, f"default-path:{base}"))
        elif _has_comsol_binary(child):
            out.append((child, f"default-path:{base}"))
    return out


def _candidates_from_path() -> list[tuple[Path, str]]:
    """`which comsol` — last-resort PATH probe."""
    out: list[tuple[Path, str]] = []
    comsol_bin = shutil.which("comsol")
    if not comsol_bin:
        return out
    p = Path(comsol_bin).resolve()
    for parent in p.parents:
        if _has_comsol_binary(parent):
            out.append((parent, "which:comsol"))
            break
    return out


_INSTALL_DIR_FINDERS: list[Callable[[], list[tuple[Path, str]]]] = [
    _candidates_from_env,
    _candidates_from_windows_defaults,
    _candidates_from_linux_defaults,
    _candidates_from_macos_defaults,
    _candidates_from_path,
]
"""Strategy chain. APPEND new finders for new install layouts; do not edit."""


# ─── core scan ────────────────────────────────────────────────────────────


def _make_install(install_dir: Path, source: str) -> SolverInstall | None:
    if not install_dir.is_dir() or not _has_comsol_binary(install_dir):
        return None
    raw_version = _read_install_version(install_dir) or "?"
    short = ".".join(raw_version.split(".")[:2]) if raw_version != "?" else "?"
    return SolverInstall(
        name="comsol",
        version=short,
        path=str(install_dir),
        source=source,
        extra={"raw_version": raw_version},
    )


def _scan_comsol_installs() -> list[SolverInstall]:
    """Find every COMSOL installation on this host. Pure stdlib.

    Walks _INSTALL_DIR_FINDERS in order, dedupes by resolved path, then
    extracts each install's version via _VERSION_PROBES. Both lists are
    open for extension — see the comment block above.
    """
    found: dict[str, SolverInstall] = {}
    for finder in _INSTALL_DIR_FINDERS:
        try:
            candidates = finder()
        except Exception:
            continue
        for path, source in candidates:
            inst = _make_install(path, source=source)
            if inst is None:
                continue
            key = str(Path(inst.path).resolve())
            found.setdefault(key, inst)
    return sorted(found.values(), key=lambda i: i.version, reverse=True)


class ComsolDriver:
    """Sim driver for COMSOL Multiphysics (via the `mph` Python binding).

    DriverProtocol surface:
        name, detect, lint, connect, parse_output, detect_installed
    """

    # Process-name substrings that identify COMSOL windows. Used by
    # Phase 3 ``GuiController`` to filter Desktop enumeration down to
    # COMSOL-owned dialogs (mphserver, ComsolUI, Cortex-style client).
    GUI_PROCESS_FILTER: tuple[str, ...] = (
        "comsol", "comsolui", "comsolmph", "mphserver", "comsolclient",
    )

    def __init__(self) -> None:
        self._jvm_started = False
        self._model_util = None  # com.comsol.model.util.ModelUtil
        self._model = None       # active COMSOL model
        self._session_id: str | None = None
        self._ui_mode: str | None = None
        self._connected_at: float | None = None
        self._run_count: int = 0
        self._last_run: dict | None = None
        self._server_proc = None
        self._client_proc = None
        self._server_log_handle: TextIO | None = None
        self._client_log_handle: TextIO | None = None
        self._server_log_path: Path | None = None
        self._client_log_path: Path | None = None
        self._desktop_pid: int | None = None
        self._active_model_tag: str | None = None
        self._server_owner: str | None = None
        self._attach_only: bool = False
        self._last_health: dict | None = None
        self._last_disconnect_reason: dict | None = None
        self._launch_options: dict = {}
        self._port: int = 2036
        # Sim dir for probe workdir (screenshots, workdir-diff baseline)
        self._sim_dir: Path = Path(os.environ.get("SIM_DIR") or (Path.cwd() / ".sim"))
        # InspectProbe list — baseline 9-channel (GUI off). launch() will
        # flip GUI probes on for server-graphics/shared-desktop modes.
        self.probes: list = _default_comsol_probes(enable_gui=False)
        self._gui = None  # GuiController; set at launch() for visible modes.

    @property
    def name(self) -> str:
        return "comsol"

    @property
    def supports_session(self) -> bool:
        return True

    def detect(self, script: Path) -> bool:
        """Detect COMSOL/MPh scripts via `import mph`."""
        text = script.read_text(encoding="utf-8")
        return bool(re.search(r"^\s*(import mph|from mph\b)", text, re.MULTILINE))

    def lint(self, script: Path) -> LintResult:
        """Validate a COMSOL/MPh script (syntax + import + Client/start hint)."""
        diagnostics: list[Diagnostic] = []
        try:
            text = script.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(level="error", message=f"cannot read file: {e}")],
            )

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
                has_client = any(
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "Client"
                    for node in ast.walk(tree)
                )
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
        """Lightweight availability check.

        We avoid importing `mph` from the core process (it pulls in JPype +
        the JVM). Instead we report whichever installs detect_installed()
        finds and let `sim env install <profile>` handle the SDK side.
        """
        installs = _scan_comsol_installs()
        if not installs:
            return ConnectionInfo(
                solver="comsol",
                version=None,
                status="not_installed",
                message="No COMSOL installation detected on this host",
            )
        top = installs[0]
        return ConnectionInfo(
            solver="comsol",
            version=top.extra.get("raw_version", top.version),
            status="ok",
            message=f"COMSOL {top.version} at {top.path}",
            solver_version=top.version,
        )

    def detect_installed(self) -> list[SolverInstall]:
        """Enumerate every COMSOL installation visible on this host.

        Strategy (in priority order; deduped by resolved install path):
          1. COMSOL_ROOT env var
          2. Default install dirs under C:\\Program Files\\COMSOL\\COMSOL{XX}\\,
             C:\\Program Files (x86)\\COMSOL64\\, /usr/local/comsol*, /opt/comsol*
          3. PATH probe via `which comsol`

        Pure Python. Does NOT import mph/jpype. Returns [] when nothing
        is found. Version is read from readme.txt's first line and
        normalized to "X.Y" form.
        """
        return _scan_comsol_installs()

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

    def run_file(self, script: Path):
        """Execute a one-shot COMSOL/MPh Python script.

        The script runs in the same interpreter sim-cli is running under.
        `mph` and its JPype/JVM dependencies must be importable in that
        env — sim-cli itself is SDK-free, so `sim env install comsol`
        (or a manual `pip install mph`) provisions the runtime.
        """
        return run_subprocess(
            [sys.executable, str(script)],
            script=script,
            solver=self.name,
        )

    # ── Persistent session via comsolmphserver + JPype ──────────────────────

    def _resolve_comsol_root(self, comsol_root: str | None) -> str:
        if comsol_root:
            return comsol_root
        env = os.environ.get("COMSOL_ROOT")
        if env:
            return env
        installs = _scan_comsol_installs()
        if installs:
            return installs[0].path
        raise RuntimeError("no COMSOL installation detected; set COMSOL_ROOT")

    def _start_jvm(self, comsol_root: str) -> None:
        if self._jvm_started:
            return
        import jpype
        import jpype.imports  # enables `from com.comsol...` Java-as-Python imports
        jre_path = os.path.join(comsol_root, "java", "win64", "jre")
        plugins_dir = os.path.join(comsol_root, "plugins")
        lib_dir = os.path.join(comsol_root, "lib", "win64")

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
            f"-Dcs.root={comsol_root}",
            f"-Djava.library.path={lib_dir}",
            convertStrings=True,
        )
        self._jvm_started = True

    def _configure_workdir(self, workspace: str | None = None, cwd: str | None = None) -> None:
        """Choose the directory where driver diagnostics and probe artifacts live."""
        base = workspace or cwd
        if base:
            self._sim_dir = Path(base) / ".sim"
        self._sim_dir.mkdir(parents=True, exist_ok=True)

    def _open_log(self, stem: str) -> tuple[Path, TextIO]:
        self._sim_dir.mkdir(parents=True, exist_ok=True)
        suffix = self._session_id or time.strftime("%Y%m%d-%H%M%S")
        path = self._sim_dir / f"{stem}-{suffix}.log"
        return path, path.open("ab")

    def _close_log_handles(self) -> None:
        for attr in ("_server_log_handle", "_client_log_handle"):
            handle = getattr(self, attr, None)
            if handle is not None:
                try:
                    handle.close()
                except Exception:
                    pass
                setattr(self, attr, None)

    def _terminate_processes(self) -> None:
        self._kill_pid(self._desktop_pid)
        self._desktop_pid = None
        attrs = ["_client_proc"]
        if self._server_owner != "external":
            attrs.append("_server_proc")
        for attr in attrs:
            proc = getattr(self, attr, None)
            if proc is None:
                continue
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass
            setattr(self, attr, None)

    def _tail_file(self, path: Path | None, max_lines: int = 40) -> str | None:
        if path is None or not path.is_file():
            return None
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return None
        return "\n".join(lines[-max_lines:])

    def _diagnostic_context(self, code: str, message: str) -> dict:
        for handle in (self._server_log_handle, self._client_log_handle):
            if handle is not None:
                try:
                    handle.flush()
                except Exception:
                    pass
        server_returncode = None
        client_returncode = None
        if self._server_proc is not None:
            server_returncode = self._server_proc.poll()
        if self._client_proc is not None:
            client_returncode = self._client_proc.poll()
        return {
            "ok": False,
            "code": code,
            "message": message,
            "port": self._port,
            "server_pid": getattr(self._server_proc, "pid", None),
            "server_returncode": server_returncode,
            "server_log_path": str(self._server_log_path) if self._server_log_path else None,
            "server_log_tail": self._tail_file(self._server_log_path),
            "client_pid": getattr(self._client_proc, "pid", None),
            "client_returncode": client_returncode,
            "client_log_path": str(self._client_log_path) if self._client_log_path else None,
            "client_log_tail": self._tail_file(self._client_log_path),
            "desktop_pid": self._desktop_pid,
            "server_owner": self._server_owner,
            "attach_only": self._attach_only,
        }

    def _lifecycle_error(self, code: str, message: str) -> ComsolLifecycleError:
        diagnostics = self._diagnostic_context(code, message)
        self._last_health = diagnostics
        return ComsolLifecycleError(message, diagnostics)

    def _classify_comsol_error(self, text: str) -> str:
        lowered = text.lower()
        if "license" in lowered or "checkout" in lowered:
            return "comsol.license_or_login"
        if "login" in lowered or "password" in lowered or "authentication" in lowered:
            return "comsol.license_or_login"
        if "connection refused" in lowered or "connection reset" in lowered:
            return "comsol.modelutil.stale"
        if "port" in lowered and ("use" in lowered or "bind" in lowered):
            return "comsol.server.port_conflict"
        if "server is busy" in lowered or "serverbusy" in lowered:
            return "comsol.server.busy_timeout"
        return "comsol.modelutil.failure"

    def _normalize_ui_mode(self, ui_mode: str | None) -> tuple[str, str | None]:
        requested = (ui_mode or "").strip().lower()
        effective = _COMSOL_UI_MODE_ALIASES.get(requested)
        if effective is None:
            valid = ", ".join(sorted(set(_COMSOL_UI_MODE_ALIASES.values())))
            raise ValueError(
                f"unknown COMSOL ui_mode={ui_mode!r}; expected one of: {valid}"
            )
        return effective, _COMSOL_UI_MODE_NOTES.get(requested)

    def _resolve_visual_mode(
        self,
        ui_mode: str | None,
        visual_mode: str | None,
    ) -> tuple[str, str | None, str | None]:
        effective, note = self._normalize_ui_mode(ui_mode)
        requested = (visual_mode or "").strip().lower()
        visual = _COMSOL_VISUAL_MODE_ALIASES.get(requested)
        if requested and requested not in _COMSOL_VISUAL_MODE_ALIASES:
            valid = ", ".join(sorted(k for k in _COMSOL_VISUAL_MODE_ALIASES if k))
            raise ValueError(
                f"unknown COMSOL visual_mode={visual_mode!r}; expected one of: {valid}"
            )
        if visual is None:
            return effective, note, None
        if visual == "server-graphics":
            return "server-graphics", "visual_mode='server-graphics' requested.", visual
        if visual == "shared-desktop":
            return (
                "shared-desktop",
                "visual_mode='shared-desktop' attaches COMSOL Desktop to the live server "
                "and routes agent edits to the Desktop active model tag.",
                visual,
            )
        return effective, note, visual

    def _ui_capabilities(self, effective_ui_mode: str | None = None) -> dict:
        mode = effective_ui_mode or self._ui_mode or "no_gui"
        server_graphics = mode == "server-graphics"
        shared_desktop = mode == "shared-desktop"
        return {
            "server_graphics": server_graphics,
            "plot_windows": server_graphics or shared_desktop,
            "model_builder_live": shared_desktop,
            "desktop_inspection": "live" if shared_desktop else "artifact",
            "shared_desktop": shared_desktop,
            "screenshot_source": "codex-desktop-or-sim-remote",
        }

    def _current_model_tag(self) -> str | None:
        if self._model is None:
            return None
        try:
            return str(self._model.tag())
        except Exception:
            return None

    def _live_model_binding_summary(
        self,
        *,
        model_tags: list[str] | None,
        current_model_tag: str | None,
    ) -> dict:
        caps = self._ui_capabilities()
        model_builder_live = bool(caps.get("model_builder_live"))
        active_tag = self._active_model_tag
        tags = model_tags or []
        sidecar_tags = [tag for tag in tags if tag != active_tag]

        ok = (
            model_builder_live
            and active_tag is not None
            and current_model_tag == active_tag
            and (not tags or active_tag in tags)
        )
        if ok:
            message = (
                f"Driver model handle is bound to live Desktop model "
                f"{active_tag!r}."
            )
        elif not model_builder_live:
            message = (
                "No live Model Builder binding for this UI mode; use "
                "visual_mode='shared-desktop' for live Desktop collaboration."
            )
        elif active_tag is None:
            message = "Shared Desktop is active, but no Desktop model tag is bound."
        elif current_model_tag != active_tag:
            message = (
                f"Driver model handle is {current_model_tag!r}, but the live "
                f"Desktop active model tag is {active_tag!r}."
            )
        else:
            message = (
                f"Live Desktop active model tag {active_tag!r} was not found "
                "in ModelUtil.tags()."
            )

        return {
            "ok": ok,
            "bound_model_tag": current_model_tag,
            "model_builder_live": model_builder_live,
            "sidecar_model_tags": sidecar_tags,
            "message": message,
        }

    def _shared_desktop_sidecar_diagnostics(
        self,
        code: str,
        *,
        observed_model_tags: list[str] | None = None,
    ) -> list[RuntimeDiagnostic]:
        if self._ui_mode != "shared-desktop":
            return []
        if not code.strip():
            return []

        try:
            tree = ast.parse(code)
        except SyntaxError:
            return []

        diagnostics: list[RuntimeDiagnostic] = []
        seen: set[tuple[str, str | None]] = set()
        active_tag = self._active_model_tag
        sidecar_tags = [
            tag for tag in (observed_model_tags or [])
            if tag != active_tag
        ]

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            if not isinstance(func.value, ast.Name) or func.value.id != "ModelUtil":
                continue
            if func.attr not in {"create", "model"}:
                continue

            target_tag = None
            if node.args and isinstance(node.args[0], ast.Constant):
                value = node.args[0].value
                if isinstance(value, str):
                    target_tag = value

            if func.attr == "model" and (
                target_tag is None or target_tag == active_tag
            ):
                continue

            key = (func.attr, target_tag)
            if key in seen:
                continue
            seen.add(key)

            if func.attr == "create":
                message = (
                    "In shared-desktop mode, ModelUtil.create(...) can create "
                    "a server-side model that the visible COMSOL Desktop is "
                    "not displaying. Prefer mutating the provided `model` "
                    "handle unless a sidecar model is intentional."
                )
            else:
                message = (
                    f"In shared-desktop mode, ModelUtil.model({target_tag!r}) "
                    f"does not match the live Desktop active model tag "
                    f"{active_tag!r}; GUI updates may appear out of sync."
                )

            diagnostics.append(RuntimeDiagnostic(
                severity="warning",
                message=message,
                source="comsol:shared-desktop",
                code="comsol.shared_desktop.sidecar_model_risk",
                extra={
                    "call": f"ModelUtil.{func.attr}",
                    "requested_tag": target_tag,
                    "active_model_tag": active_tag,
                    "observed_model_tags": list(observed_model_tags or []),
                    "sidecar_model_tags": sidecar_tags,
                },
            ))

        return diagnostics

    def _windows_process_rows(self) -> list[dict]:
        if os.name != "nt":
            return []
        import csv
        import subprocess

        try:
            result = subprocess.run(
                ["tasklist", "/fo", "csv", "/nh"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return []
        if result.returncode != 0:
            return []
        rows: list[dict] = []
        for row in csv.reader(result.stdout.splitlines()):
            if len(row) < 2:
                continue
            try:
                pid = int(row[1])
            except ValueError:
                continue
            rows.append({"name": row[0], "pid": pid})
        return rows

    def _comsol_process_pids(self) -> set[int]:
        pids: set[int] = set()
        for row in self._windows_process_rows():
            name = str(row.get("name", "")).lower()
            if any(part in name for part in self.GUI_PROCESS_FILTER):
                pids.add(int(row["pid"]))
        return pids

    def _kill_pid(self, pid: int | None) -> None:
        if pid is None:
            return
        if os.name == "nt":
            import subprocess

            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            return
        try:
            os.kill(pid, 9)
        except OSError:
            pass

    def _start_desktop_client(
        self,
        bin_dir: str,
        host: str = "localhost",
        before_pids: set[int] | None = None,
        timeout_s: float = 45,
    ) -> None:
        import subprocess

        client_exe = os.path.join(bin_dir, "comsol.exe")
        if not os.path.isfile(client_exe):
            raise RuntimeError(f"COMSOL Desktop launcher not found at {client_exe}")

        self._client_log_path, self._client_log_handle = self._open_log("comsol-mphclient")
        client_args = [
            client_exe,
            "mphclient",
            "-host",
            host,
            "-port",
            str(self._port),
        ]
        self._client_proc = subprocess.Popen(
            client_args,
            stdout=self._client_log_handle,
            stderr=subprocess.STDOUT,
        )

        before_pids = before_pids or set()
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            for window in self._visible_windows(include_untracked_comsol=True):
                pid = int(window.get("pid") or 0)
                title = str(window.get("title") or "")
                if pid in before_pids:
                    continue
                if "COMSOL Multiphysics" in title:
                    self._desktop_pid = pid
                    return
            time.sleep(1)

        # The launcher commonly exits after spawning ComsolUI.exe; an already
        # open port and later health check can still prove the session. Keep
        # going, but expose the missing Desktop PID in health.

    def _visible_windows(self, include_untracked_comsol: bool = False) -> list[dict]:
        """Best-effort visible COMSOL windows for tracked server/client PIDs."""
        if os.name != "nt":
            return []

        tracked = {
            getattr(self._server_proc, "pid", None): "server",
            getattr(self._client_proc, "pid", None): "client",
            self._desktop_pid: "desktop",
        }
        tracked.pop(None, None)
        process_names = {
            int(row["pid"]): str(row["name"]).lower()
            for row in self._windows_process_rows()
        }
        if not tracked and not include_untracked_comsol:
            return []

        try:
            import ctypes
            import ctypes.wintypes

            user32 = ctypes.windll.user32
            windows: list[dict] = []

            @ctypes.WINFUNCTYPE(
                ctypes.wintypes.BOOL,
                ctypes.wintypes.HWND,
                ctypes.wintypes.LPARAM,
            )
            def enum_window(hwnd, _lparam):
                if not user32.IsWindowVisible(hwnd):
                    return True
                pid = ctypes.wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                role = tracked.get(int(pid.value))
                if role is None and not include_untracked_comsol:
                    return True
                title = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(hwnd, title, 512)
                process_name = process_names.get(int(pid.value), "")
                if role is None and include_untracked_comsol:
                    if any(part in process_name for part in self.GUI_PROCESS_FILTER):
                        role = "desktop" if "comsolui" in process_name else "comsol"
                if title.value and role is not None:
                    windows.append({
                        "pid": int(pid.value),
                        "role": role,
                        "title": title.value,
                        "process": process_name,
                    })
                return True

            user32.EnumWindows(enum_window, 0)
            return windows
        except Exception:
            return []

    def _bind_model(
        self,
        ModelUtil,
        *,
        preferred_tag: str | None = None,
        wait_for_tag: bool = False,
        timeout_s: float = 45,
        allow_remove_stale: bool = False,
    ) -> None:
        model_tag = preferred_tag or "Model1"
        deadline = time.time() + timeout_s
        while wait_for_tag and time.time() < deadline:
            tags = [str(tag) for tag in list(ModelUtil.tags())]
            if model_tag in tags:
                break
            if tags and preferred_tag is None:
                model_tag = tags[0]
                break
            time.sleep(1)

        try:
            tags = [str(tag) for tag in list(ModelUtil.tags())]
            if model_tag in tags:
                self._model = ModelUtil.model(model_tag)
            elif tags and preferred_tag is None and not allow_remove_stale:
                model_tag = tags[0]
                self._model = ModelUtil.model(model_tag)
            else:
                try:
                    self._model = ModelUtil.create(model_tag)
                except Exception:
                    if not allow_remove_stale:
                        raise
                    for stale in list(ModelUtil.tags()):
                        try:
                            ModelUtil.remove(stale)
                        except Exception:
                            pass
                    try:
                        self._model = ModelUtil.create(model_tag)
                    except Exception:
                        model_tag = f"Model_{uuid.uuid4().hex[:6]}"
                        self._model = ModelUtil.create(model_tag)
            self._active_model_tag = str(self._model.tag())
        except Exception as exc:  # noqa: BLE001 - Java exceptions vary by version
            code = self._classify_comsol_error(str(exc))
            action = "bind" if not allow_remove_stale else "create"
            raise self._lifecycle_error(
                code,
                f"ModelUtil.{action} failed for tag {model_tag!r}: {exc}",
            ) from exc

    def health(self) -> dict:
        """Best-effort live-session health for `session.summary` / diagnostics."""
        server_returncode = self._server_proc.poll() if self._server_proc is not None else None
        client_returncode = self._client_proc.poll() if self._client_proc is not None else None
        server_running = (
            self._server_proc is not None and server_returncode is None
        )
        port_open = self._check_port(self._port, timeout=0.5)
        modelutil_connected: bool | None = None
        model_tags: list[str] | None = None
        code = "comsol.session.connected"
        message = "COMSOL session is connected"

        if self._model_util is not None:
            try:
                model_tags = [str(tag) for tag in list(self._model_util.tags())]
                modelutil_connected = True
            except Exception as exc:  # noqa: BLE001 - Java exceptions vary by version
                modelutil_connected = False
                code = self._classify_comsol_error(str(exc))
                message = f"ModelUtil health check failed: {exc}"

        current_model_tag = self._current_model_tag()

        if self._model is None:
            code = "comsol.session.disconnected"
            message = "No active COMSOL model is attached"
        elif self._server_proc is not None and server_returncode is not None:
            code = "comsol.server.process_exited"
            message = f"comsolmphserver exited with return code {server_returncode}"
        elif self._server_proc is not None and not port_open:
            code = "comsol.server.port_closed"
            message = f"COMSOL server port {self._port} is not reachable"

        connected = (
            self._model is not None
            and (self._server_proc is None or server_returncode is None)
            and (self._server_proc is None or port_open)
            and modelutil_connected is not False
        )
        health = {
            "ok": connected,
            "connected": connected,
            "code": code,
            "message": message,
            "session_id": self._session_id,
            "ui_mode": self._ui_mode,
            "requested_ui_mode": self._launch_options.get("requested_ui_mode"),
            "effective_ui_mode": self._ui_mode,
            "ui_note": self._launch_options.get("ui_note"),
            "ui_capabilities": self._ui_capabilities(),
            "port": self._port,
            "server_pid": getattr(self._server_proc, "pid", None),
            "server_owner": self._server_owner,
            "attach_only": self._attach_only,
            "server_running": server_running,
            "server_returncode": server_returncode,
            "server_log_path": str(self._server_log_path) if self._server_log_path else None,
            "server_log_tail": self._tail_file(self._server_log_path) if not connected else None,
            "client_pid": getattr(self._client_proc, "pid", None),
            "client_returncode": client_returncode,
            "desktop_pid": self._desktop_pid,
            "client_log_path": str(self._client_log_path) if self._client_log_path else None,
            "modelutil_connected": modelutil_connected,
            "model_tags": model_tags,
            "active_model_tag": self._active_model_tag,
            "live_model_binding": self._live_model_binding_summary(
                model_tags=model_tags,
                current_model_tag=current_model_tag,
            ),
            "windows": self._visible_windows(),
            "last_disconnect_reason": self._last_disconnect_reason,
            "launch_options": self._launch_options,
        }
        self._last_health = health
        return health

    def query(self, name: str) -> dict:
        if name in {"health", "session.health"}:
            return self.health()
        if name in {"ui.modes", "session.ui_modes"}:
            return {
                "ok": True,
                "modes": {
                    "no_gui": "COMSOL server API session without intentional visible UI.",
                    "server-graphics": (
                        "COMSOL server API session with server-side graphics; "
                        "plot windows may be visible, but Model Builder is not "
                        "attached live."
                    ),
                    "desktop-inspection": (
                        "Save the .mph artifact, then open it in full COMSOL "
                        "Desktop for Model Builder inspection. This is not "
                        "live-synchronized with the server session."
                    ),
                    "shared-desktop": (
                        "Full COMSOL Desktop attached to the same server, with "
                        "agent edits routed to the Desktop active model tag."
                    ),
                },
                "aliases": dict(_COMSOL_UI_MODE_ALIASES),
            }
        return {"ok": False, "error": f"unknown inspect target: {name}"}

    def _check_port(self, port: int, timeout: float = 2) -> bool:
        import socket
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=timeout):
                return True
        except OSError:
            return False

    def _wait_for_port(self, port: int, timeout: float = 90) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._server_proc is not None and self._server_proc.poll() is not None:
                raise self._lifecycle_error(
                    "comsol.server.process_exited",
                    "comsolmphserver exited before its port became ready",
                )
            if self._check_port(port, timeout=2):
                return True
            time.sleep(2)
        return False

    def launch(
        self,
        mode: str = "solver",
        ui_mode: str = "no_gui",
        processors: int = 2,
        comsol_root: str | None = None,
        user: str | None = None,
        password: str | None = None,
        **kwargs,
    ) -> dict:
        """Launch comsolmphserver and connect via JPype.

        1. Start `comsolmphserver.exe` as compute backend, or attach to an
           externally managed server when `attach_only=true`
        2. Wait for the target port to listen
        3. Connect via `ModelUtil.connect()` from JPype
        4. If ui_mode resolves to 'server-graphics', keep COMSOL server-side
           graphics enabled so plot windows can appear. If visual_mode resolves
           to 'shared-desktop', launch COMSOL Desktop and bind the driver to
           the Desktop active model tag.
        """
        import subprocess

        workspace = kwargs.pop("workspace", None)
        cwd = kwargs.pop("cwd", None)
        port = kwargs.pop("port", None)
        attach_only = _as_bool(kwargs.pop("attach_only", False))
        server_host = kwargs.pop("server_host", kwargs.pop("host", "localhost"))
        model_tag = kwargs.pop("model_tag", None)
        visual_mode = kwargs.pop("visual_mode", None)
        desktop_timeout = float(kwargs.pop("desktop_timeout", 45))
        requested_ui_mode = ui_mode
        effective_ui_mode, ui_note, normalized_visual_mode = self._resolve_visual_mode(
            ui_mode,
            visual_mode,
        )
        if port is not None:
            self._port = int(port)
        self._session_id = str(uuid.uuid4())
        self._configure_workdir(workspace=workspace, cwd=cwd)
        self._last_health = None
        self._last_disconnect_reason = None
        self._desktop_pid = None
        self._active_model_tag = None
        self._attach_only = attach_only
        self._server_owner = "external" if attach_only else "plugin"

        root = self._resolve_comsol_root(comsol_root)
        user = user or os.environ.get("COMSOL_USER", "")
        password = password or os.environ.get("COMSOL_PASSWORD", "")
        bin_dir = os.path.join(root, "bin", "win64")
        server_exe = os.path.join(bin_dir, "comsolmphserver.exe")

        if not os.path.isfile(server_exe):
            raise RuntimeError(f"comsolmphserver not found at {server_exe}")

        self._launch_options = {
            "mode": mode,
            "requested_ui_mode": requested_ui_mode,
            "ui_mode": effective_ui_mode,
            "ui_note": ui_note,
            "requested_visual_mode": visual_mode,
            "visual_mode": normalized_visual_mode,
            "desktop_timeout": desktop_timeout,
            "attach_only": attach_only,
            "server_owner": self._server_owner,
            "server_host": server_host,
            "model_tag": model_tag,
            "processors": processors,
            "comsol_root": root,
            "workspace": workspace,
            "cwd": cwd,
            "port": self._port,
            **kwargs,
        }

        before_comsol_pids = self._comsol_process_pids()
        if attach_only:
            if not self._check_port(self._port, timeout=2):
                err = self._lifecycle_error(
                    "comsol.server.attach_port_closed",
                    f"attach_only requested but {server_host}:{self._port} is not reachable",
                )
                self._close_log_handles()
                raise err
        else:
            self._server_log_path, self._server_log_handle = self._open_log("comsol-mphserver")

            if self._check_port(self._port, timeout=0.5):
                err = self._lifecycle_error(
                    "comsol.server.port_conflict",
                    f"port {self._port} is already accepting connections before launch",
                )
                self._close_log_handles()
                raise err

            # -login auto: use cached credentials set via `comsolmphserver -login force`
            server_args = [
                server_exe,
                "-port", str(self._port),
                "-multi", "on",
                "-login", "auto",
                "-silent",
            ]
            if effective_ui_mode == "server-graphics":
                server_args += ["-graphics", "-3drend", "sw"]
            self._server_proc = subprocess.Popen(
                server_args,
                stdout=self._server_log_handle,
                stderr=subprocess.STDOUT,
            )

            try:
                port_ready = self._wait_for_port(self._port, timeout=90)
            except ComsolLifecycleError:
                self._terminate_processes()
                self._close_log_handles()
                raise

            if not port_ready:
                err = self._lifecycle_error(
                    "comsol.server.port_timeout",
                    f"comsolmphserver did not start listening on port {self._port} within 90s",
                )
                self._terminate_processes()
                self._close_log_handles()
                raise err

        # Connect JPype first (lightweight, doesn't grab an exclusive lock)
        # so the GUI client launching next won't race us on "Server is in
        # use by another client". Then start the GUI, and poll ModelUtil
        # until the GUI's auto-created Untitled model appears — adopt it
        # so driver + GUI share the same Java object.
        try:
            self._start_jvm(root)
            from com.comsol.model.util import ModelUtil  # type: ignore
        except Exception as exc:  # noqa: BLE001 - JPype/JVM failures vary by install
            err = self._lifecycle_error(
                "comsol.jvm.start_failed",
                f"failed to start COMSOL JVM: {exc}",
            )
            self._terminate_processes()
            self._close_log_handles()
            raise err from exc

        try:
            if user and password:
                ModelUtil.connect(server_host, self._port, user, password)
            else:
                ModelUtil.connect(server_host, self._port)
        except Exception as exc:  # noqa: BLE001 - Java exceptions vary by version
            code = self._classify_comsol_error(str(exc))
            err = self._lifecycle_error(
                code,
                f"ModelUtil.connect failed: {exc}",
            )
            self._terminate_processes()
            self._close_log_handles()
            raise err from exc

        from com.comsol.model.util import ServerBusyHandler  # type: ignore
        ModelUtil.setServerBusyHandler(ServerBusyHandler(30000))
        self._model_util = ModelUtil

        if effective_ui_mode == "shared-desktop":
            try:
                self._start_desktop_client(
                    bin_dir,
                    host=server_host,
                    before_pids=before_comsol_pids,
                    timeout_s=desktop_timeout,
                )
            except Exception as exc:  # noqa: BLE001 - Desktop launch failures vary
                err = self._lifecycle_error(
                    "comsol.desktop.launch_failed",
                    f"failed to launch COMSOL Desktop client: {exc}",
                )
                self._terminate_processes()
                self._close_log_handles()
                raise err from exc

            try:
                self._bind_model(
                    ModelUtil,
                    preferred_tag=model_tag,
                    wait_for_tag=True,
                    timeout_s=desktop_timeout,
                    allow_remove_stale=False,
                )
            except ComsolLifecycleError as err:
                self._terminate_processes()
                self._close_log_handles()
                raise err
        elif attach_only:
            try:
                self._bind_model(
                    ModelUtil,
                    preferred_tag=model_tag,
                    wait_for_tag=False,
                    timeout_s=desktop_timeout,
                    allow_remove_stale=False,
                )
            except ComsolLifecycleError as err:
                self._terminate_processes()
                self._close_log_handles()
                raise err
        else:
            # Create model. Guard against the server surviving a previous
            # disconnect(): if "Model1" already exists on the server, that tag
            # belongs to a stale session — remove it first, then create fresh.
            # Fallback: if removal is refused, create with a session-unique name
            # so we never conflict.
            try:
                self._bind_model(
                    ModelUtil,
                    preferred_tag=model_tag,
                    allow_remove_stale=True,
                )
            except ComsolLifecycleError as err:
                self._terminate_processes()
                self._close_log_handles()
                raise err

        self._ui_mode = effective_ui_mode
        self._connected_at = time.time()
        self._run_count = 0
        self._last_run = None
        self._last_health = self.health()

        # Flip probes to GUI-aware variant + construct gui actuation facade
        # when visible COMSOL windows may appear. no_gui launches skip both.
        gui_mode = effective_ui_mode in {"server-graphics", "shared-desktop"}
        if gui_mode:
            self.probes = _default_comsol_probes(enable_gui=True)
            from sim.gui import GuiController  # noqa: PLC0415
            self._gui = GuiController(
                process_name_substrings=self.GUI_PROCESS_FILTER,
                workdir=str(self._sim_dir),
            )

        return {
            "ok": True,
            "session_id": self._session_id,
            "mode": "client-server",
            "source": "launch",
            "requested_ui_mode": requested_ui_mode,
            "ui_mode": effective_ui_mode,
            "effective_ui_mode": effective_ui_mode,
            "ui_note": ui_note,
            "ui_capabilities": self._ui_capabilities(effective_ui_mode),
            "port": self._port,
            "server_owner": self._server_owner,
            "attach_only": self._attach_only,
            "model_tag": str(self._model.tag()),
            "active_model_tag": self._active_model_tag,
            "desktop_pid": self._desktop_pid,
            "server_log_path": str(self._server_log_path) if self._server_log_path else None,
            "client_log_path": str(self._client_log_path) if self._client_log_path else None,
            "launch_options": self._launch_options,
            "health": self._last_health,
        }

    def run(
        self, code: str, label: str = "comsol-snippet",
        timeout_s: float | None = None,
    ) -> dict:
        """Execute a Python snippet with `model` and `ModelUtil` in scope.

        Phase 2 additions:
          - `timeout_s`: per-snippet deadline (default 300s via
            `sim._timeout.DEFAULT_TIMEOUT_S`). Hung snippets return
            ok=False and the probe layer emits `sim.runtime.snippet_timeout`.
          - Returns `diagnostics[]` and `artifacts[]` populated by the
            driver's probe list (9-channel coverage).
        """
        if self._model is None:
            health = self.health()
            return {
                "run_id": str(uuid.uuid4()),
                "ok": False,
                "label": label,
                "stdout": "",
                "stderr": "",
                "error": health["message"],
                "result": None,
                "elapsed_s": 0,
                "diagnostics": [],
                "artifacts": [],
                "health": health,
            }

        preflight_health = self.health()
        if not preflight_health.get("connected", False):
            return {
                "run_id": str(uuid.uuid4()),
                "ok": False,
                "label": label,
                "stdout": "",
                "stderr": "",
                "error": preflight_health["message"],
                "result": None,
                "elapsed_s": 0,
                "diagnostics": [],
                "artifacts": [],
                "health": preflight_health,
            }

        from sim._timeout import call_with_timeout, DEFAULT_TIMEOUT_S  # noqa: PLC0415

        namespace: dict = {
            "model": self._model,
            "ModelUtil": self._model_util,
            "_result": None,
        }
        if self._gui is not None:
            namespace["gui"] = self._gui

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        error: str | None = None
        ok = True
        started_at = time.time()

        # Snapshot workdir BEFORE exec for WorkdirDiffProbe
        workdir_path = Path(self._sim_dir)
        try:
            workdir_path.mkdir(parents=True, exist_ok=True)
            before = sorted(
                str(p.relative_to(workdir_path)).replace("\\", "/")
                for p in workdir_path.rglob("*") if p.is_file()
            )
        except Exception:
            before = []

        def _run_snippet():
            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                exec(code, namespace)  # noqa: S102

        timeout_budget = (
            DEFAULT_TIMEOUT_S if timeout_s is None else timeout_s
        )
        t_result = call_with_timeout(_run_snippet, timeout_s=timeout_budget)
        hung = t_result.hung
        if hung:
            ok = False
            error = (
                f"snippet exceeded timeout_s={timeout_budget} "
                f"(hung in COMSOL call; session is likely unusable — "
                f"disconnect and re-launch)"
            )
            self._last_health = {
                **self._diagnostic_context(
                    "comsol.runtime.timeout_session_unhealthy",
                    error,
                ),
                "connected": False,
            }
        elif t_result.exception is not None:
            ok = False
            exc = t_result.exception
            error = "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )
            self._last_health = {
                **self._diagnostic_context(
                    self._classify_comsol_error(error),
                    "COMSOL snippet failed",
                ),
                "connected": False,
            }

        elapsed = round(time.time() - started_at, 4)
        self._run_count += 1

        if namespace.get("model") is not self._model and namespace.get("model") is not None:
            self._model = namespace["model"]

        observed_model_tags: list[str] | None = None
        if self._model_util is not None:
            try:
                observed_model_tags = [
                    str(tag) for tag in list(self._model_util.tags())
                ]
            except Exception:
                observed_model_tags = None

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

        # ── inspect probe pipeline (Phase 2) ───────────────────────────────
        session_ns: dict = {}
        if self._model is not None:
            session_ns["session"] = self._model
        if error:
            session_ns["_session_error"] = error
        if record["result"] is not None:
            session_ns["_result"] = record["result"]

        extras: dict = {}
        if hung:
            extras["timeout_hit"] = True
            extras["timeout_s"] = timeout_budget
            extras["timeout_elapsed_s"] = elapsed

        ctx = InspectCtx(
            stdout=record["stdout"] or "",
            stderr=record["stderr"] or "",
            workdir=str(workdir_path),
            wall_time_s=elapsed,
            exit_code=0 if ok else 1,
            driver_name=self.name,
            session_ns=session_ns,
            workdir_before=before,
            extras=extras,
        )
        diags, arts = collect_diagnostics(self.probes, ctx)
        diags.extend(self._shared_desktop_sidecar_diagnostics(
            code,
            observed_model_tags=observed_model_tags,
        ))
        record["diagnostics"] = [d.to_dict() for d in diags]
        record["artifacts"] = [a.to_dict() for a in arts]
        record["health"] = self._last_health if not ok else preflight_health

        self._last_run = record
        return record

    def disconnect(self) -> None:
        reason = self.health()
        if self._model_util is not None:
            try:
                self._model_util.disconnect()
            except Exception:
                pass
        self._terminate_processes()
        self._close_log_handles()
        self._model = None
        self._gui = None
        self._model_util = None
        reason.update({
            "ok": False,
            "connected": False,
            "code": "comsol.session.disconnected",
            "message": "disconnect() was called",
        })
        self._last_disconnect_reason = reason
        self._last_health = reason
        self._session_id = None
        self._connected_at = None
        self._active_model_tag = None
        self._server_owner = None
        self._attach_only = False
        self._run_count = 0
        self._last_run = None
