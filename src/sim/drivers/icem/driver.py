"""Ansys ICEM CFD driver for sim.

Architecture: **Pure CLI Orchestration** (same family as CFX). ICEM has
no Python SDK — it ships a Tcl scripting engine embedded in
``med_batch.exe``. The canonical headless path is:

    icemcfd.bat -batch -script <file.tcl>

which sets up PATH (Qt, HDF5, MKL, OpenJRE) and delegates to
``med_batch.exe``.

Detection is regex on ``ic_`` Tcl commands (``ic_geo_*``, ``ic_uns_*``,
``ic_hex_*``, ``ic_boco_*``). These are ICEM's proprietary Tcl API
and do not appear in any other Tcl codebase.

Phase 1 (this file): one-shot ``sim run script.tcl --solver icem``.
No session mode — ICEM meshing is inherently batch-oriented.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from sim.driver import ConnectionInfo, Diagnostic, LintResult, SolverInstall
from sim.runner import run_subprocess

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Tcl commands unique to ICEM CFD — any of these is strong evidence.
_ICEM_TCL_MARKERS = re.compile(
    r"^\s*(ic_geo_|ic_uns_|ic_hex_|ic_boco_|ic_load_|ic_save_|ic_delete_|"
    r"ic_set_|ic_flood_|ic_run_|ic_meshing_|ic_domain_|ic_topo_|"
    r"ic_curve_|ic_surface_|ic_point_|ic_param_|ic_batch_|"
    r"fluent_write_input|ic_Mesher\b)",
    re.MULTILINE,
)

# Broader Tcl keywords that might appear alongside ic_* commands
_TCL_PROC = re.compile(r"^\s*(proc |package require |source |set |puts |foreach |if \{)", re.MULTILINE)

_ICEMCFD_ROOT_RE = re.compile(r"^ICEMCFD_ROOT(\d{3})$")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_icemcfd_bat(root: Path) -> Path | None:
    """Return ``<root>/win64_amd/bin/icemcfd.bat`` if present."""
    bat = root / "win64_amd" / "bin" / "icemcfd.bat"
    if bat.is_file():
        return bat
    # Linux layout
    bat = root / "linux64" / "bin" / "icemcfd"
    if bat.is_file():
        return bat
    return None


def _find_med_batch(root: Path) -> Path | None:
    """Return ``<root>/win64_amd/bin/med_batch.exe`` if present."""
    for sub in ("win64_amd", "linux64"):
        exe = root / sub / "bin" / ("med_batch.exe" if os.name == "nt" else "med_batch")
        if exe.is_file():
            return exe
    return None


def _scan_icem_roots() -> list[tuple[str, Path]]:
    """Scan env for ``ICEMCFD_ROOT<xxx>`` vars."""
    out: list[tuple[str, Path]] = []
    for k, v in os.environ.items():
        m = _ICEMCFD_ROOT_RE.match(k)
        if not m:
            continue
        root = Path(v)
        if not root.is_dir():
            continue
        vnum = m.group(1)
        ver = f"{vnum[:2]}.{vnum[2]}"
        out.append((ver, root))
    return sorted(out, key=lambda x: x[0], reverse=True)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


class IcemDriver:
    """ICEM CFD driver (Phase 1 — one-shot batch Tcl)."""

    @property
    def name(self) -> str:
        return "icem"

    @property
    def supports_session(self) -> bool:
        return False

    # ------------------------------------------------------------------
    # detect / lint
    # ------------------------------------------------------------------

    def detect(self, script: Path) -> bool:
        if not script.is_file():
            return False
        # Accept .tcl, .rpl (ICEM replay), .tk
        if script.suffix.lower() not in (".tcl", ".rpl", ".tk"):
            return False
        try:
            text = script.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        return bool(_ICEM_TCL_MARKERS.search(text))

    def lint(self, script: Path) -> LintResult:
        if not script.is_file():
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(level="error", message=f"File not found: {script}")],
            )
        text = script.read_text(encoding="utf-8", errors="replace")
        diagnostics: list[Diagnostic] = []

        # Check file extension
        if script.suffix.lower() not in (".tcl", ".rpl", ".tk"):
            diagnostics.append(Diagnostic(
                level="warning",
                message=f"Unexpected extension {script.suffix}; ICEM scripts are typically .tcl or .rpl",
            ))

        # Check for ICEM markers
        has_markers = bool(_ICEM_TCL_MARKERS.search(text))
        if not has_markers:
            if _TCL_PROC.search(text):
                diagnostics.append(Diagnostic(
                    level="error",
                    message="Script is Tcl but contains no ICEM CFD commands (ic_*). Is this an ICEM script?",
                ))
            else:
                diagnostics.append(Diagnostic(
                    level="error",
                    message="No ICEM CFD commands (ic_*) found in the script.",
                ))

        # Basic Tcl brace-balance check (catches common copy-paste errors)
        open_braces = text.count("{")
        close_braces = text.count("}")
        if open_braces != close_braces:
            diagnostics.append(Diagnostic(
                level="error",
                message=f"Unbalanced braces: {open_braces} open vs {close_braces} close. Tcl will fail to parse.",
            ))

        ok = not any(d.level == "error" for d in diagnostics)
        return LintResult(ok=ok, diagnostics=diagnostics)

    # ------------------------------------------------------------------
    # connect / detect_installed
    # ------------------------------------------------------------------

    def connect(self) -> ConnectionInfo:
        installs = self.detect_installed()
        if not installs:
            return ConnectionInfo(
                solver="icem",
                version=None,
                status="not_installed",
                message=(
                    "ICEM CFD not found. Set ICEMCFD_ROOT<ver> or install "
                    "Ansys with the ICEM CFD component."
                ),
            )
        top = installs[0]
        return ConnectionInfo(
            solver="icem",
            version=top.version,
            status="ok",
            message=f"ICEM CFD {top.version} at {top.path}",
            solver_version=top.version,
        )

    def detect_installed(self) -> list[SolverInstall]:
        out: list[SolverInstall] = []
        for ver, root in _scan_icem_roots():
            bat = _find_icemcfd_bat(root)
            med = _find_med_batch(root)
            if bat or med:
                out.append(SolverInstall(
                    name="icem",
                    version=ver,
                    path=str((bat or med).parent),
                    source="env:ICEMCFD_ROOT",
                    extra={
                        "icemcfd_bat": str(bat) if bat else None,
                        "med_batch": str(med) if med else None,
                        "root": str(root),
                    },
                ))
        return out

    # ------------------------------------------------------------------
    # run / parse_output
    # ------------------------------------------------------------------

    def parse_output(self, stdout: str) -> dict:
        """Last JSON line convention."""
        for line in reversed(stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        return {}

    def run_file(self, script: Path):
        """Execute an ICEM Tcl script via icemcfd.bat -batch -script.

        Uses ``icemcfd.bat`` which sets up PATH (Qt, HDF5, MKL, OpenJRE)
        then delegates to ``med_batch.exe``. Falls back to direct
        ``med_batch.exe -script`` if the bat is missing.
        """
        installs = self.detect_installed()
        if not installs:
            raise FileNotFoundError(
                "ICEM CFD not installed — set ICEMCFD_ROOT<ver>"
            )

        top = installs[0]
        bat = top.extra.get("icemcfd_bat")
        med = top.extra.get("med_batch")

        if bat:
            # icemcfd.bat is a CMD batch — must go through cmd.exe
            cmd = ["cmd", "/c", bat, "-batch", "-script", str(script)]
        elif med:
            cmd = [med, "-script", str(script)]
        else:
            raise FileNotFoundError("Neither icemcfd.bat nor med_batch.exe found")

        return run_subprocess(cmd, script=script, solver=self.name)
