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
from typing import Callable

from sim.driver import ConnectionInfo, Diagnostic, LintResult, SolverInstall
from sim.inspect import (
    DomainExceptionMapProbe,
    GuiDialogProbe,
    InspectCtx,
    ScreenshotProbe,
    SdkAttributeProbe,
    TextStreamRulesProbe,
    collect_diagnostics,
    generic_probes,
)
from sim.runner import run_subprocess


# ── Channel #2 — JVM/JPype-oriented stderr rules (COMSOL-specific) ─────────────
# pyfluent swallows stderr; COMSOL's JPype bridge does NOT, so real JVM
# warnings/errors make it through.
_COMSOL_STDERR_RULES: list[dict] = [
    {"pattern": r"^\[ERROR\]", "severity": "error", "code": "comsol.jvm.error"},
    {"pattern": r"^\[WARN\]", "severity": "warning", "code": "comsol.jvm.warning"},
    {"pattern": r"com\.comsol\.util\.exceptions\.FlException",
     "severity": "error", "code": "comsol.java.fl_exception"},
    {"pattern": r"did not converge", "severity": "error",
     "code": "comsol.solve.not_converged"},
    {"pattern": r"^Exception in thread", "severity": "error",
     "code": "comsol.jvm.exception"},
    # JPype-wrapped NullPointerException (common when calling Java API with
    # bad tag on uninitialized feature)
    {"pattern": r"java\.lang\.NullPointerException",
     "severity": "error", "code": "comsol.java.npe"},
]


# ── Channel #5 — COMSOL python.* → comsol.* exception upgrade rules ────────────
_COMSOL_EXC_MAP_RULES: list[dict] = [
    # Feature tag not found: Java throws "No feature with tag 'xyz'"
    {
        "code_in": ("python.Exception", "python.RuntimeError",
                    "python.java.lang.IllegalArgumentException"),
        "regex": r"No feature with tag '(\S+?)'",
        "upgrade_code": "comsol.feature.not_found",
        "message_template": "COMSOL feature tag not found: '{group1}'",
    },
    # JPype-exposed ModelClient surface: agent tries `model.feature(...)`
    # but that method doesn't exist on the raw Java client (exists on MPh's
    # Python wrapper only). This is a common agent typo pattern.
    {
        "code_in": ("python.AttributeError",),
        "regex": r"'com\.comsol[^']*' object has no attribute '(\w+)'",
        "upgrade_code": "comsol.sdk.method_not_found",
        "message_template": (
            "COMSOL Java client has no method '{group1}' — did you mean "
            "an MPh-wrapper method? Drill into the API tree explicitly "
            "(e.g. model.component('comp1').physics('solid').feature('xyz'))."
        ),
    },
    # Generic FlException surfacing as Python exception (via JPype wrapper).
    # pyfluent uses different patterns, but COMSOL's JPype bridge raises
    # Python Exception with message "Java Exception" when propagating a
    # server-side FlException — plus a second diag carrying the full Java
    # class name in `code`. We match the first one on message=="Java Exception".
    {
        "code_in": ("python.Exception",),
        "regex": r"^Java Exception$",
        "upgrade_code": "comsol.java.fl_exception",
        "message_template": (
            "COMSOL Java exception propagated through JPype "
            "(check prior traceback diag for the precise Java class)"
        ),
    },
    {
        "code_in": ("python.RuntimeError", "python.Exception"),
        "regex": r"com\.comsol\.util\.exceptions\.FlException",
        "upgrade_code": "comsol.java.fl_exception",
        "message_template": "COMSOL Java FlException: {orig}",
    },
    # Solver didn't converge / failed to find solution
    {
        "code_in": ("python.RuntimeError", "python.Exception"),
        "regex": r"(Failed to find a solution|did not converge)",
        "upgrade_code": "comsol.solve.failed",
        "message_template": "COMSOL solve failed: {match}",
    },
    # Null pointer when calling into un-initialized Java object
    {
        "code_in": ("python.RuntimeError", "python.AttributeError"),
        "regex": r"java\.lang\.NullPointerException",
        "upgrade_code": "comsol.java.null_pointer",
        "message_template": "COMSOL Java NullPointerException — object uninitialized",
    },
]


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


def _default_comsol_probes(enable_gui: bool = False) -> list:
    """COMSOL's probe list — generic base + COMSOL-specific channels.

    Generic (from generic_probes()):
      #1  ProcessMetaProbe         exit_code + wall_time
      #1+ RuntimeTimeoutProbe      hung-snippet detection
      #3  StdoutJsonTailProbe      last JSON line / _result fallback
      #3+ PythonTracebackProbe     structured traceback parsing
      #9  WorkdirDiffProbe         new files → Artifacts (always last)

    COMSOL-specific:
      #2  TextStreamRulesProbe(stderr)  JVM/JPype-flavored error patterns
      #4  SdkAttributeProbe(readers=)  Java-API style attribute readers
      #5  DomainExceptionMapProbe       COMSOL-specific exception upgrade rules
      #6  NOT wired — COMSOL session has no TUI concept
      #7  NOT wired — COMSOL has no per-session transcript
      #8a GuiDialogProbe               Cortex/COMSOL windows (gui mode)
      #8b ScreenshotProbe              per-window PNG crops (gui mode)
    """
    from sim.inspect import generic_probes
    _g = {p.name: p for p in generic_probes()}
    probes: list = [
        _g["process-meta"],                                              # #1  通用
        _g["runtime-timeout"],                                           # #1+ 通用
        TextStreamRulesProbe(                                            # #2  COMSOL 专用
            source="stderr",
            text_selector=lambda ctx: ctx.stderr,
            rules=_COMSOL_STDERR_RULES,
        ),
        _g["stdout-json-tail"],                                          # #3  通用
        _g["python-traceback"],                                          # #3+ 通用
        SdkAttributeProbe(                                               # #4  COMSOL 专用
            readers=_default_comsol_readers(),
            source_prefix="sdk:attr",
            code_prefix="comsol.sdk.attr",
        ),
        # #6 TUI: intentionally not wired — COMSOL has no TUI in session mode
        # #7 Log file: intentionally not wired — COMSOL has no per-session
        #    transcript. Global %USERPROFILE%\.comsol\...\log is too noisy.
        DomainExceptionMapProbe(rules=_COMSOL_EXC_MAP_RULES),            # #5  post-processor
    ]
    if enable_gui:
        probes.append(GuiDialogProbe(                                    # #8a COMSOL 专用
            process_name_substrings=("comsol", "comsolui", "mphserver"),
            code_prefix="comsol.gui",
        ))
        probes.append(ScreenshotProbe(                                   # #8b COMSOL 专用
            filename_prefix="comsol_shot",
            process_name_substrings=("comsol", "comsolui", "mphserver"),
        ))
    probes.append(_g["workdir-diff"])                                    # #9  通用（始终最后）
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
    """Windows: C:\\Program Files\\COMSOL\\COMSOL{XX}\\Multiphysics\\ etc."""
    bases = [
        Path(r"C:\Program Files\COMSOL"),
        Path(r"C:\Program Files (x86)\COMSOL"),
        Path(r"C:\Program Files (x86)\COMSOL64\Multiphysics"),
        Path(r"D:\Program Files\COMSOL"),
        Path(r"D:\Program Files (x86)\COMSOL64\Multiphysics"),
        Path(r"E:\Program Files (x86)\COMSOL64\Multiphysics"),
    ]
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
        self._port: int = 2036
        # Sim dir for probe workdir (screenshots, workdir-diff baseline)
        self._sim_dir: Path = Path(os.environ.get("SIM_DIR") or (Path.cwd() / ".sim"))
        # InspectProbe list — baseline 9-channel (GUI off). launch() will
        # flip GUI probes on if ui_mode='gui'/'desktop'.
        self.probes: list = _default_comsol_probes(enable_gui=False)
        self._gui = None  # GuiController; set at launch() when ui_mode=gui

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
        text = script.read_text(encoding="utf-8")
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

    def _wait_for_port(self, port: int, timeout: float = 90) -> bool:
        import socket
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=2):
                    return True
            except OSError:
                time.sleep(2)
        return False

    def launch(
        self,
        mode: str = "solver",
        ui_mode: str = "gui",
        processors: int = 2,
        comsol_root: str | None = None,
        user: str | None = None,
        password: str | None = None,
    ) -> dict:
        """Launch comsolmphserver + optional GUI client, connect via JPype.

        1. Start `comsolmphserver.exe` as compute backend
        2. Wait for it to listen on the port
        3. Connect via `ModelUtil.connect()` from JPype
        4. If ui_mode == 'gui', launch `comsolmphclient.exe` (visual GUI attached)
        """
        import subprocess

        root = self._resolve_comsol_root(comsol_root)
        user = user or os.environ.get("COMSOL_USER", "")
        password = password or os.environ.get("COMSOL_PASSWORD", "")
        bin_dir = os.path.join(root, "bin", "win64")
        server_exe = os.path.join(bin_dir, "comsolmphserver.exe")
        client_exe = os.path.join(bin_dir, "comsolmphclient.exe")

        if not os.path.isfile(server_exe):
            raise RuntimeError(f"comsolmphserver not found at {server_exe}")

        # -login auto: use cached credentials set via `comsolmphserver -login force`
        self._server_proc = subprocess.Popen(
            [server_exe, "-port", str(self._port), "-multi", "on",
             "-login", "auto", "-silent", "-graphics", "-3drend", "sw"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        if not self._wait_for_port(self._port, timeout=90):
            self._server_proc.kill()
            self._server_proc = None
            raise RuntimeError(
                f"comsolmphserver did not start listening on port {self._port} "
                "within 90s — check COMSOL license"
            )

        # Connect JPype first (lightweight, doesn't grab an exclusive lock)
        # so the GUI client launching next won't race us on "Server is in
        # use by another client". Then start the GUI, and poll ModelUtil
        # until the GUI's auto-created Untitled model appears — adopt it
        # so driver + GUI share the same Java object.
        self._start_jvm(root)
        from com.comsol.model.util import ModelUtil  # type: ignore

        if user and password:
            ModelUtil.connect("localhost", self._port, user, password)
        else:
            ModelUtil.connect("localhost", self._port)

        from com.comsol.model.util import ServerBusyHandler  # type: ignore
        ModelUtil.setServerBusyHandler(ServerBusyHandler(30000))
        self._model_util = ModelUtil

        if ui_mode in ("gui", "desktop") and os.path.isfile(client_exe):
            client_args = [client_exe, "-port", str(self._port), "-login", "auto"]
            cs_user = os.environ.get("COMSOL_USER")
            cs_pass = os.environ.get("COMSOL_PASSWORD")
            if cs_user and cs_pass:
                client_args += ["-username", cs_user, "-password", cs_pass]
            self._client_proc = subprocess.Popen(
                client_args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        # Poll up to 90s for the GUI client to create its Untitled model.
        # Fall back to ModelUtil.create("Model1") in headless/standalone.
        self._model = None
        if ui_mode in ("gui", "desktop"):
            deadline = time.time() + 90
            while time.time() < deadline:
                tags = list(ModelUtil.tags())
                if tags:
                    self._model = ModelUtil.model(tags[0])
                    break
                time.sleep(1)
        if self._model is None:
            self._model = ModelUtil.create("Model1")

        self._session_id = str(uuid.uuid4())
        self._ui_mode = ui_mode
        self._connected_at = time.time()
        self._run_count = 0
        self._last_run = None

        # Flip probes to GUI-aware variant + construct gui actuation facade
        # when the client window is actually up. Headless launches skip both.
        gui_mode = ui_mode in ("gui", "desktop")
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
            "ui_mode": ui_mode,
            "port": self._port,
            "model_tag": str(self._model.tag()),
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
            raise RuntimeError("No active COMSOL session — call launch() first")

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
        elif t_result.exception is not None:
            ok = False
            exc = t_result.exception
            error = "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )

        elapsed = round(time.time() - started_at, 4)
        self._run_count += 1

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
        record["diagnostics"] = [d.to_dict() for d in diags]
        record["artifacts"] = [a.to_dict() for a in arts]

        self._last_run = record
        return record

    def disconnect(self) -> None:
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
        self._gui = None
        self._model_util = None
        self._session_id = None
        self._connected_at = None
        self._run_count = 0
        self._last_run = None
