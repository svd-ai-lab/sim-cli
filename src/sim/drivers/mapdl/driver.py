"""ANSYS MAPDL driver for sim.

Phase 1: one-shot batch execution via ANSYS242.exe / MAPDL242.exe.

MAPDL consumes APDL input decks such as ``.inp`` and ``.mac`` files. The
shortest reliable automation path is native batch mode:

    ANSYS242.exe -np 1 -b -j jobname -i input.inp -o jobname.out
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from sim.driver import ConnectionInfo, Diagnostic, LintResult, RunResult, SolverInstall

_SCAN_DRIVES = ("C", "D", "E", "F", "G")
_SUPPORTED_SUFFIXES = {".inp", ".mac"}
_VERSIONED_EXECUTABLE_RE = re.compile(r"^(ANSYS|MAPDL)(\d{3})\.exe$", re.IGNORECASE)


def _normalize_version_token(token: str | None) -> str | None:
    """Normalize MAPDL version tokens to short form (e.g. ``242`` -> ``24.2``)."""
    if token is None:
        return None
    text = str(token).strip()
    if not text:
        return None

    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) == 3:
        return f"{digits[:2]}.{digits[2]}"
    if len(digits) >= 2 and "." in text:
        parts = text.split(".")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            return f"{parts[0]}.{parts[1]}"
    if len(digits) == 5 and "r" in text.lower():
        return f"{digits[2:4]}.{digits[4]}"
    return None


def _make_install(exe_path: Path, source: str, version_hint: str | None = None) -> SolverInstall | None:
    if not exe_path.is_file():
        return None

    version = _normalize_version_token(version_hint)
    if version is None:
        match = _VERSIONED_EXECUTABLE_RE.match(exe_path.name)
        if match:
            version = _normalize_version_token(match.group(2))
    if version is None:
        path_text = str(exe_path)
        env_match = re.search(r"AWP_ROOT(\d{3})", path_text, re.IGNORECASE)
        dir_match = re.search(r"[\\/]v(\d{3})(?:[\\/]|$)", path_text, re.IGNORECASE)
        if env_match:
            version = _normalize_version_token(env_match.group(1))
        elif dir_match:
            version = _normalize_version_token(dir_match.group(1))
    if version is None:
        return None

    try:
        install_root = exe_path.parents[3]
    except IndexError:
        install_root = exe_path.parent

    return SolverInstall(
        name="mapdl",
        version=version,
        path=str(install_root),
        source=source,
        extra={
            "exe_path": str(exe_path),
            "product": exe_path.stem.upper(),
            "release_label": install_root.name if install_root != exe_path.parent else version,
        },
    )


def _env_candidates() -> list[tuple[Path, str, str | None]]:
    out: list[tuple[Path, str, str | None]] = []
    for key, value in os.environ.items():
        match = re.fullmatch(r"AWP_ROOT(\d{3})", key, re.IGNORECASE)
        if not match or not value:
            continue
        root = Path(value)
        digits = match.group(1)
        for name in (f"ANSYS{digits}.exe", f"MAPDL{digits}.exe", "ANSYS.exe", "MAPDL.exe"):
            exe = root / "ansys" / "bin" / "winx64" / name
            out.append((exe, f"env:{key}", digits))
    return out


def _path_candidates() -> list[tuple[Path, str, str | None]]:
    out: list[tuple[Path, str, str | None]] = []
    for name in ("ansys242", "mapdl242", "ANSYS242.exe", "MAPDL242.exe", "ansys", "mapdl"):
        resolved = shutil.which(name)
        if not resolved:
            continue
        path = Path(resolved).resolve()
        match = _VERSIONED_EXECUTABLE_RE.match(path.name)
        digits = match.group(2) if match else None
        out.append((path, f"which:{name}", digits))
    return out


def _default_windows_candidates() -> list[tuple[Path, str, str | None]]:
    out: list[tuple[Path, str, str | None]] = []
    base_templates = [
        r"{drive}:\Program Files\ANSYS Inc",
        r"{drive}:\Program Files (x86)\ANSYS Inc",
        r"{drive}:\ansys\ansys\ANSYS Inc",
        r"{drive}:\ANSYS Inc",
    ]
    for drive in _SCAN_DRIVES:
        for template in base_templates:
            base = Path(template.format(drive=drive))
            if not base.is_dir():
                continue
            for child in sorted(base.iterdir(), reverse=True):
                version_match = re.fullmatch(r"v(\d{3})", child.name, re.IGNORECASE)
                if not version_match:
                    continue
                digits = version_match.group(1)
                for name in (f"ANSYS{digits}.exe", f"MAPDL{digits}.exe"):
                    out.append((
                        child / "ansys" / "bin" / "winx64" / name,
                        f"default-path:{base}",
                        digits,
                    ))
    return out


def _scan_mapdl_installs() -> list[SolverInstall]:
    found: dict[str, SolverInstall] = {}
    for finder in (_env_candidates, _path_candidates, _default_windows_candidates):
        try:
            candidates = finder()
        except Exception:
            continue
        for exe_path, source, version_hint in candidates:
            inst = _make_install(exe_path, source=source, version_hint=version_hint)
            if inst is None:
                continue
            key = str(Path(inst.path).resolve())
            if key in found:
                continue
            found[key] = inst
    return sorted(found.values(), key=lambda item: item.version, reverse=True)


def _safe_jobname(name: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_]", "_", name).strip("_")
    return text or "mapdl_job"


class MapdlDriver:
    """sim driver for ANSYS MAPDL one-shot batch runs."""

    @property
    def name(self) -> str:
        return "mapdl"

    def detect(self, script: Path) -> bool:
        return script.suffix.lower() in _SUPPORTED_SUFFIXES

    def lint(self, script: Path) -> LintResult:
        if not self.detect(script):
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(
                    level="error",
                    message=f"Unsupported MAPDL file type '{script.suffix}'. Expected .inp or .mac.",
                )],
            )

        try:
            text = script.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(level="error", message=f"Cannot read file: {exc}")],
            )

        if not text.strip():
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(level="error", message="MAPDL input deck is empty")],
            )

        return LintResult(ok=True, diagnostics=[])

    def connect(self) -> ConnectionInfo:
        installs = self.detect_installed()
        if not installs:
            return ConnectionInfo(
                solver="mapdl",
                version=None,
                status="not_installed",
                message="No MAPDL installation detected on this host",
            )
        top = installs[0]
        return ConnectionInfo(
            solver="mapdl",
            version=top.version,
            status="ok",
            message=f"MAPDL {top.version} found at {top.extra.get('exe_path', top.path)}",
            solver_version=top.version,
        )

    def detect_installed(self) -> list[SolverInstall]:
        return _scan_mapdl_installs()

    def parse_output(self, stdout: str) -> dict:
        for line in reversed(stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        return {}

    def run_file(self, script: Path) -> RunResult:
        installs = self.detect_installed()
        if not installs:
            raise RuntimeError(
                "ANSYS MAPDL not found. Install MAPDL or set an AWP_ROOT### environment variable."
            )

        install = installs[0]
        exe_path = install.extra.get("exe_path")
        if not exe_path:
            raise RuntimeError("Detected MAPDL installation is missing exe_path metadata")

        script = script.resolve()
        jobname = _safe_jobname(script.stem)
        out_path = script.parent / f"{jobname}.out"
        command = [
            str(exe_path),
            "-np",
            "1",
            "-b",
            "-j",
            jobname,
            "-i",
            script.name,
            "-o",
            out_path.name,
        ]

        start = time.monotonic()
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            cwd=str(script.parent),
        )
        duration = time.monotonic() - start

        stdout_parts: list[str] = []
        if proc.stdout.strip():
            stdout_parts.append(proc.stdout.strip())
        if out_path.is_file():
            stdout_parts.append(out_path.read_text(encoding="utf-8", errors="replace").strip())

        return RunResult(
            exit_code=proc.returncode,
            stdout="\n".join(part for part in stdout_parts if part),
            stderr=proc.stderr.strip(),
            duration_s=round(duration, 3),
            script=str(script),
            solver=self.name,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
