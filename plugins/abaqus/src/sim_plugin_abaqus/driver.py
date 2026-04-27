"""Abaqus driver for sim.

Abaqus is a commercial FEA solver by Dassault Systemes SIMULIA. Execution
is via the ``abaqus`` command-line tool:
  - Input decks (.inp): ``abaqus job=<name> input=<file> interactive``
  - Python scripts (.py): ``abaqus cae noGUI=<file>``

This driver is pure subprocess — it never imports Abaqus internals (which
live in Abaqus's own embedded Python, not the system Python). Detection
scans for the ``abaqus.bat`` / ``abq20XX.bat`` launcher in standard
SIMULIA install paths.
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from sim.driver import ConnectionInfo, Diagnostic, LintResult, RunResult, SolverInstall

# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------

_ABAQUS_IMPORT_RE = re.compile(
    r"^\s*(from\s+abaqus\b|from\s+abaqusConstants\b|import\s+abaqus\b)",
    re.MULTILINE,
)

_INP_KEYWORD_RE = re.compile(r"^\*\w+", re.MULTILINE)


def _find_abaqus_bat(commands_dir: Path) -> Path | None:
    """Return the highest-version abqNNNN.bat in a Commands directory."""
    if not commands_dir.is_dir():
        return None
    bats = sorted(commands_dir.glob("abq*.bat"), reverse=True)
    for bat in bats:
        if bat.name.startswith("abq") and bat.name != "abq_cae_open.bat" and bat.name != "abq_odb_open.bat":
            return bat
    return None


def _version_from_bat_name(bat: Path) -> str | None:
    """Extract version year from bat name: abq2026.bat -> '2026'."""
    m = re.search(r"abq(\d{4})", bat.name)
    return m.group(1) if m else None


def _version_from_info(abaqus_cmd: str) -> str | None:
    """Run ``abaqus information=release`` and parse version string."""
    try:
        result = subprocess.run(
            [abaqus_cmd, "information=release"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    # Parse "Abaqus 2026" from output
    m = re.search(r"Abaqus\s+(\d{4})", result.stdout)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Install-dir finders (strategy chain — append new finders, don't modify)
# ---------------------------------------------------------------------------


def _candidates_from_env() -> list[tuple[Path, str]]:
    """Check SIMULIA_HOME and ABAQUS_BAT_PATH env vars."""
    out: list[tuple[Path, str]] = []
    for var in ("SIMULIA_HOME", "ABAQUS_BAT_PATH"):
        val = os.environ.get(var)
        if val:
            p = Path(val)
            if p.is_file() and p.suffix == ".bat":
                out.append((p.parent, f"env:{var}"))
            elif p.is_dir():
                commands = p / "Commands"
                if commands.is_dir():
                    out.append((commands, f"env:{var}"))
                elif (p / "abaqus.bat").is_file() or _find_abaqus_bat(p):
                    out.append((p, f"env:{var}"))
    return out


def _candidates_from_defaults() -> list[tuple[Path, str]]:
    """Scan standard SIMULIA install directories on Windows."""
    bases = []
    for drive in ("C", "D", "E"):
        bases.extend([
            Path(f"{drive}:/Program Files (x86)/Dassault Systemes/SIMULIA/Commands"),
            Path(f"{drive}:/Program Files/Dassault Systemes/SIMULIA/Commands"),
            Path(f"{drive}:/SIMULIA/Commands"),
            Path(f"{drive}:/Program Files (x86)/SIMULIA/Commands"),
        ])
    out: list[tuple[Path, str]] = []
    for base in bases:
        if base.is_dir():
            out.append((base, f"default-path:{base}"))
    return out


def _candidates_from_path() -> list[tuple[Path, str]]:
    """``which abaqus`` — last-resort PATH probe."""
    out: list[tuple[Path, str]] = []
    abaqus_bin = shutil.which("abaqus")
    if abaqus_bin:
        p = Path(abaqus_bin).resolve()
        out.append((p.parent, "which:abaqus"))
    return out


_INSTALL_FINDERS = [
    _candidates_from_env,
    _candidates_from_defaults,
    _candidates_from_path,
]


def _scan_abaqus_installs() -> list[SolverInstall]:
    """Find every Abaqus installation on this host. Pure stdlib."""
    found: dict[str, SolverInstall] = {}

    for finder in _INSTALL_FINDERS:
        try:
            candidates = finder()
        except Exception:
            continue
        for commands_dir, source in candidates:
            bat = _find_abaqus_bat(commands_dir)
            if bat is None:
                # Try abaqus.bat directly
                ab = commands_dir / "abaqus.bat"
                if ab.is_file():
                    bat = ab
                else:
                    continue

            key = str(bat.resolve())
            if key in found:
                continue

            version = _version_from_bat_name(bat) or "unknown"
            found[key] = SolverInstall(
                name="abaqus",
                version=version,
                path=str(commands_dir),
                source=source,
                extra={"bat": str(bat)},
            )

    return sorted(found.values(), key=lambda i: i.version, reverse=True)


# ---------------------------------------------------------------------------
# Driver class
# ---------------------------------------------------------------------------


class AbaqusDriver:
    """Sim driver for Dassault Systemes SIMULIA Abaqus.

    DriverProtocol surface:
        name, detect, lint, connect, parse_output, run_file, detect_installed
    """

    @property
    def name(self) -> str:
        return "abaqus"

    @property
    def supports_session(self) -> bool:
        return False

    # -- detect ---------------------------------------------------------------

    def detect(self, script: Path) -> bool:
        """Detect Abaqus scripts: .inp files or .py with Abaqus imports."""
        try:
            if script.suffix.lower() == ".inp":
                text = script.read_text(encoding="utf-8", errors="replace")
                return bool(_INP_KEYWORD_RE.search(text))
            if script.suffix.lower() == ".py":
                text = script.read_text(encoding="utf-8", errors="replace")
                return bool(_ABAQUS_IMPORT_RE.search(text))
        except (OSError, UnicodeDecodeError):
            pass
        return False

    # -- lint -----------------------------------------------------------------

    def lint(self, script: Path) -> LintResult:
        """Validate an Abaqus script or input deck."""
        diagnostics: list[Diagnostic] = []
        suffix = script.suffix.lower()

        try:
            text = script.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(level="error", message=f"Cannot read file: {e}")],
            )

        if suffix == ".inp":
            return self._lint_inp(text, diagnostics)
        elif suffix == ".py":
            return self._lint_py(text, diagnostics)
        else:
            diagnostics.append(
                Diagnostic(
                    level="error",
                    message=f"Unsupported file type: {suffix} (expected .inp or .py)",
                )
            )
            return LintResult(ok=False, diagnostics=diagnostics)

    def _lint_inp(self, text: str, diagnostics: list[Diagnostic]) -> LintResult:
        """Lint an Abaqus .inp input deck."""
        has_keyword = bool(_INP_KEYWORD_RE.search(text))
        if not has_keyword:
            diagnostics.append(
                Diagnostic(level="error", message="No Abaqus keywords found (expected *KEYWORD lines)")
            )

        has_step = bool(re.search(r"^\*STEP", text, re.MULTILINE | re.IGNORECASE))
        if not has_step:
            diagnostics.append(
                Diagnostic(
                    level="warning",
                    message="No *STEP keyword found — input deck may not define an analysis step",
                )
            )

        ok = not any(d.level == "error" for d in diagnostics)
        return LintResult(ok=ok, diagnostics=diagnostics)

    def _lint_py(self, text: str, diagnostics: list[Diagnostic]) -> LintResult:
        """Lint an Abaqus Python script."""
        has_import = bool(_ABAQUS_IMPORT_RE.search(text))
        if not has_import:
            diagnostics.append(
                Diagnostic(level="error", message="No Abaqus import found (expected 'from abaqus import *')")
            )

        try:
            ast.parse(text)
        except SyntaxError as e:
            diagnostics.append(
                Diagnostic(level="error", message=f"Syntax error: {e}", line=e.lineno)
            )

        ok = not any(d.level == "error" for d in diagnostics)
        return LintResult(ok=ok, diagnostics=diagnostics)

    # -- connect / detect_installed -------------------------------------------

    def connect(self) -> ConnectionInfo:
        """Lightweight availability check via detect_installed."""
        installs = self.detect_installed()
        if not installs:
            return ConnectionInfo(
                solver="abaqus",
                version=None,
                status="not_installed",
                message="No Abaqus installation detected on this host",
            )
        top = installs[0]
        return ConnectionInfo(
            solver="abaqus",
            version=top.version,
            status="ok",
            message=f"Abaqus {top.version} at {top.path}",
            solver_version=top.version,
        )

    def detect_installed(self) -> list[SolverInstall]:
        """Scan for Abaqus installations. Pure stdlib, no SDK import."""
        return _scan_abaqus_installs()

    # -- parse_output ---------------------------------------------------------

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

    # -- run_file -------------------------------------------------------------

    def run_file(self, script: Path) -> RunResult:
        """Execute an Abaqus script or input deck.

        - .inp: ``abaqus job=<stem> input=<file> interactive``
        - .py:  ``abaqus cae noGUI=<file>``
        """
        installs = self.detect_installed()
        if not installs:
            raise RuntimeError("Abaqus is not installed on this host")

        abaqus_bat = installs[0].extra.get("bat", "abaqus")
        suffix = script.suffix.lower()
        work_dir = script.parent

        if suffix == ".inp":
            job_name = script.stem
            cmd = [abaqus_bat, f"job={job_name}", f"input={script.name}", "interactive"]
        elif suffix == ".py":
            cmd = [abaqus_bat, "cae", f"noGUI={script}"]
        else:
            cmd = [abaqus_bat, "cae", f"noGUI={script}"]

        start = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(work_dir),
                timeout=600,
            )
        except subprocess.TimeoutExpired:
            duration = time.monotonic() - start
            return RunResult(
                exit_code=-1,
                stdout="",
                stderr="Abaqus execution timed out after 600s",
                duration_s=round(duration, 3),
                script=str(script),
                solver=self.name,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        duration = time.monotonic() - start

        return RunResult(
            exit_code=proc.returncode,
            stdout=proc.stdout.strip() if proc.stdout else "",
            stderr=proc.stderr.strip() if proc.stderr else "",
            duration_s=round(duration, 3),
            script=str(script),
            solver=self.name,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
