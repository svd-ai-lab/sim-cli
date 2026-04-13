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
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Callable

from sim.driver import ConnectionInfo, Diagnostic, LintResult, SolverInstall
from sim.runner import run_subprocess


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

    @property
    def name(self) -> str:
        return "comsol"

    @property
    def supports_session(self) -> bool:
        return False

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
