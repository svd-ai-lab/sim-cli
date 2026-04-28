"""Elmer FEM driver for sim.

Elmer FEM is an open-source multi-physics FEM suite from CSC-IT (Finland).
Cases are defined by:
    case.sif   — Solver Input File (text block-structured)
    mesh/      — mesh directory (with mesh.header, mesh.nodes, etc.)

Execution: ``ElmerSolver case.sif``. The .sif's Header block references
the mesh directory via ``Mesh DB "." "mesh"``.

Output:
    case.vtu   — ParaView file (name from `Post File =` in Simulation block)
    log        — captured from stdout by sim
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


_BLOCK_RE = re.compile(
    r"^\s*(Header|Simulation|Constants|Body|Material|Body\s+Force|"
    r"Equation|Solver|Boundary\s+Condition|Initial\s+Condition)\b",
    re.MULTILINE | re.IGNORECASE,
)
_HEADER_RE = re.compile(r"^\s*Header\b", re.MULTILINE | re.IGNORECASE)
_SIMULATION_RE = re.compile(r"^\s*Simulation\b", re.MULTILINE | re.IGNORECASE)
_SOLVER_RE = re.compile(r"^\s*Solver\s+\d*\b", re.MULTILINE | re.IGNORECASE)


def _version_from_elmer(elmer_bin: Path) -> str | None:
    """Parse `ElmerSolver -v` / banner. Look for 'Elmer 9.x' or 'version X'."""
    env = os.environ.copy()
    # lib dir
    for libdir in (elmer_bin.parent.parent / "lib" / "elmersolver",
                   elmer_bin.parent.parent / "lib"):
        if libdir.is_dir():
            env["LD_LIBRARY_PATH"] = f"{libdir}:{env.get('LD_LIBRARY_PATH','')}"
            break
    try:
        proc = subprocess.run(
            [str(elmer_bin), "-v"],
            capture_output=True, text=True, timeout=10, env=env,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    out = (proc.stdout or "") + (proc.stderr or "")
    # "Elmer SVN revision: 7ed1..." or "Elmer 9.0 Yyyy-Mm-Dd"
    m = re.search(r"Elmer\s+(\d+\.\d+(?:\.\d+)?)", out)
    if m:
        return m.group(1)
    m = re.search(r"version\s+(\d+\.\d+(?:\.\d+)?)", out, re.IGNORECASE)
    if m:
        return m.group(1)
    # release-26.1 style: elmer printed "26.1" somewhere? fallback to banner
    m = re.search(r"\b(\d+\.\d+)\b", out)
    return m.group(1) if m else None


def _make_install(elmer_bin: Path, source: str) -> SolverInstall | None:
    if not elmer_bin.is_file():
        return None
    version = _version_from_elmer(elmer_bin) or "unknown"
    extra = {"bin": str(elmer_bin)}
    # Find LD_LIBRARY_PATH candidate
    for libdir in (elmer_bin.parent.parent / "lib" / "elmersolver",
                   elmer_bin.parent.parent / "lib"):
        if libdir.is_dir():
            extra["ld_library_path"] = str(libdir)
            break
    return SolverInstall(
        name="elmer", version=version,
        path=str(elmer_bin.parent), source=source, extra=extra,
    )


def _candidates_from_env() -> list[tuple[Path, str]]:
    out = []
    for var in ("ELMER_HOME", "ELMER_BIN"):
        val = os.environ.get(var)
        if not val:
            continue
        p = Path(val)
        if p.is_file():
            out.append((p, f"env:{var}"))
        elif p.is_dir():
            cand = p / "bin" / "ElmerSolver"
            if cand.is_file():
                out.append((cand, f"env:{var}"))
    return out


def _candidates_from_default() -> list[tuple[Path, str]]:
    bases = [
        Path("/data/Chenyx/sim/opt/elmer/bin"),
        Path("/opt/elmer/bin"),
        Path("/usr/bin"),
        Path("/usr/local/bin"),
    ]
    out = []
    for base in bases:
        cand = base / "ElmerSolver"
        if cand.is_file():
            out.append((cand, f"default-path:{base}"))
    return out


def _candidates_from_path() -> list[tuple[Path, str]]:
    out = []
    p = shutil.which("ElmerSolver")
    if p:
        out.append((Path(p).resolve(), "which:ElmerSolver"))
    return out


_FINDERS = [_candidates_from_env, _candidates_from_default, _candidates_from_path]


def _scan_elmer_installs() -> list[SolverInstall]:
    found: dict[str, SolverInstall] = {}
    for f in _FINDERS:
        try:
            cands = f()
        except Exception:
            continue
        for b, s in cands:
            key = str(b.resolve())
            if key in found:
                continue
            inst = _make_install(b, s)
            if inst is not None:
                found[key] = inst
    return sorted(found.values(), key=lambda i: i.version, reverse=True)


class ElmerDriver:
    """Sim driver for Elmer FEM (open-source multi-physics FEM)."""

    @property
    def name(self) -> str:
        return "elmer"

    @property
    def supports_session(self) -> bool:
        return False

    def detect(self, script: Path) -> bool:
        try:
            if script.suffix.lower() != ".sif":
                return False
            text = script.read_text(encoding="utf-8", errors="replace")
            return bool(_BLOCK_RE.search(text))
        except (OSError, UnicodeDecodeError):
            return False

    def lint(self, script: Path) -> LintResult:
        diagnostics: list[Diagnostic] = []
        if script.suffix.lower() != ".sif":
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(
                    level="error",
                    message=f"Unsupported file type: {script.suffix} (expected .sif)",
                )],
            )
        try:
            text = script.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(level="error", message=f"Cannot read: {e}")],
            )

        if not _HEADER_RE.search(text):
            diagnostics.append(Diagnostic(
                level="error",
                message="No `Header` block — Elmer needs Header with Mesh DB reference",
            ))
        if not _SIMULATION_RE.search(text):
            diagnostics.append(Diagnostic(
                level="error",
                message="No `Simulation` block — Elmer needs Simulation Type etc.",
            ))
        if not _SOLVER_RE.search(text):
            diagnostics.append(Diagnostic(
                level="warning",
                message="No `Solver N` block — case will not execute any solver",
            ))

        ok = not any(d.level == "error" for d in diagnostics)
        return LintResult(ok=ok, diagnostics=diagnostics)

    def connect(self) -> ConnectionInfo:
        installs = self.detect_installed()
        if not installs:
            return ConnectionInfo(
                solver="elmer", version=None, status="not_installed",
                message="ElmerSolver binary not found",
            )
        top = installs[0]
        return ConnectionInfo(
            solver="elmer", version=top.version, status="ok",
            message=f"Elmer FEM {top.version} at {top.path}",
            solver_version=top.version,
        )

    def detect_installed(self) -> list[SolverInstall]:
        return _scan_elmer_installs()

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
            raise RuntimeError("Elmer FEM is not installed on this host")
        if script.suffix.lower() != ".sif":
            raise RuntimeError(f"Elmer only accepts .sif solver input files (got {script.suffix})")

        top = installs[0]
        elmer_bin = top.extra.get("bin", "ElmerSolver")
        work_dir = script.parent

        env = os.environ.copy()
        ld = top.extra.get("ld_library_path")
        if ld:
            env["LD_LIBRARY_PATH"] = f"{ld}:{env.get('LD_LIBRARY_PATH', '')}"

        start = time.monotonic()
        try:
            proc = subprocess.run(
                [elmer_bin, script.name],
                capture_output=True, text=True,
                cwd=str(work_dir), env=env, timeout=1800,
            )
        except subprocess.TimeoutExpired:
            return RunResult(
                exit_code=-1, stdout="",
                stderr="ElmerSolver timed out after 1800s",
                duration_s=round(time.monotonic() - start, 3),
                script=str(script), solver=self.name,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        duration = time.monotonic() - start

        return RunResult(
            exit_code=proc.returncode,
            stdout=proc.stdout.strip() if proc.stdout else "",
            stderr=proc.stderr.strip() if proc.stderr else "",
            duration_s=round(duration, 3),
            script=str(script), solver=self.name,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    # Session lifecycle stubs — one-shot driver, but DriverProtocol is
    # runtime_checkable so every method must exist. See `sim.driver`.
    def launch(self, **kwargs) -> dict:
        raise NotImplementedError(f"{self.name} driver does not support sessions")

    def run(self, code: str, label: str = "") -> dict:
        raise NotImplementedError(f"{self.name} driver does not support sessions")

    def disconnect(self) -> dict:
        return {"ok": True, "disconnected": True}
