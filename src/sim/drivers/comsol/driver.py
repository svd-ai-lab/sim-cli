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
from pathlib import Path

from sim.driver import ConnectionInfo, Diagnostic, LintResult, SolverInstall


# Default install paths probed in order. The driver dedupes by resolved path.
_WINDOWS_DEFAULT_DIRS: tuple[Path, ...] = (
    Path(r"C:\Program Files\COMSOL"),
    Path(r"C:\Program Files (x86)\COMSOL64\Multiphysics"),
    Path(r"E:\Program Files (x86)\COMSOL64\Multiphysics"),
    Path(r"D:\Program Files\COMSOL"),
)
_LINUX_DEFAULT_DIRS: tuple[Path, ...] = (
    Path("/usr/local"),
    Path("/opt"),
)


def _read_version_from_readme(install_dir: Path) -> str | None:
    """COMSOL ships a readme.txt whose first line is 'COMSOL X.Y.Z.BBB README'."""
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
    if not m:
        return None
    return m.group(1)


def _has_comsol_binary(install_dir: Path) -> bool:
    """Verify a candidate dir actually contains a comsol binary."""
    candidates = [
        install_dir / "bin" / "win64" / "comsol.exe",
        install_dir / "bin" / "win64" / "comsolmphserver.exe",
        install_dir / "bin" / "comsol",
        install_dir / "bin" / "glnxa64" / "comsol",
    ]
    return any(p.exists() for p in candidates)


def _make_install(install_dir: Path, source: str) -> SolverInstall | None:
    if not install_dir.is_dir() or not _has_comsol_binary(install_dir):
        return None
    raw_version = _read_version_from_readme(install_dir) or "?"
    short = ".".join(raw_version.split(".")[:2]) if raw_version != "?" else "?"
    return SolverInstall(
        name="comsol",
        version=short,
        path=str(install_dir),
        source=source,
        extra={"raw_version": raw_version},
    )


def _scan_comsol_installs() -> list[SolverInstall]:
    """Find every COMSOL installation on this host. Pure stdlib."""
    found: dict[str, SolverInstall] = {}

    def _record(p: Path, source: str) -> None:
        inst = _make_install(p, source=source)
        if inst is None:
            return
        key = str(Path(inst.path).resolve())
        found.setdefault(key, inst)

    # 1) COMSOL_ROOT env var (canonical signal)
    root = os.environ.get("COMSOL_ROOT")
    if root:
        _record(Path(root), source="env:COMSOL_ROOT")

    # 2) Default install dirs
    for base in _WINDOWS_DEFAULT_DIRS:
        if not base.is_dir():
            continue
        # If `base` itself contains bin/win64/comsol.exe, it's already a Multiphysics dir.
        if _has_comsol_binary(base):
            _record(base, source=f"default-path:{base}")
            continue
        # Otherwise look for COMSOL{XX}/Multiphysics/ children.
        for child in sorted(base.iterdir()):
            mp = child / "Multiphysics"
            if mp.is_dir():
                _record(mp, source=f"default-path:{base}")
            elif _has_comsol_binary(child):
                _record(child, source=f"default-path:{base}")

    for base in _LINUX_DEFAULT_DIRS:
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            n = child.name.lower()
            if "comsol" not in n:
                continue
            mp = child / "multiphysics"
            if mp.is_dir():
                _record(mp, source=f"default-path:{base}")
            elif _has_comsol_binary(child):
                _record(child, source=f"default-path:{base}")

    # 3) PATH probe — last resort
    comsol_bin = shutil.which("comsol")
    if comsol_bin:
        # comsol typically lives at <install>/bin/<arch>/comsol — walk up to install root
        p = Path(comsol_bin).resolve()
        for parent in p.parents:
            if _has_comsol_binary(parent):
                _record(parent, source="which:comsol")
                break

    return sorted(found.values(), key=lambda i: i.version, reverse=True)


class ComsolDriver:
    """Sim driver for COMSOL Multiphysics (via the `mph` Python binding).

    DriverProtocol surface:
        name, detect, lint, connect, parse_output, detect_installed
    """

    @property
    def name(self) -> str:
        return "comsol"

    def detect(self, script: Path) -> bool:
        """Detect COMSOL/MPh scripts via `import mph`."""
        text = script.read_text()
        return bool(re.search(r"^\s*(import mph|from mph\b)", text, re.MULTILINE))

    def lint(self, script: Path) -> LintResult:
        """Validate a COMSOL/MPh script (syntax + import + Client/start hint)."""
        text = script.read_text()
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
