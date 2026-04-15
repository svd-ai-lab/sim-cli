"""CalculiX driver for sim.

CalculiX (CCX) is an open-source FEA solver by Guido Dhondt. It reads
Abaqus-dialect .inp input decks and writes .frd (field results) and
.dat (text tables from *NODE PRINT / *EL PRINT).

Execution model:
    ccx <jobname>         # note: no .inp extension, jobname = stem

Output files written next to the .inp:
    <jobname>.frd         # field results (binary or ASCII)
    <jobname>.dat         # text output from *NODE PRINT / *EL PRINT
    <jobname>.sta         # convergence status

This driver is pure subprocess — ccx is a native binary, no Python SDK.
On Linux, ccx links against libspooles which may live outside the system
path; we set LD_LIBRARY_PATH when running.
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

# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

_INP_KEYWORD_RE = re.compile(r"^\*\w+", re.MULTILINE)


def _version_from_ccx(ccx_bin: Path) -> str | None:
    """Run `ccx -v` to extract version. Some builds have no banner."""
    env = os.environ.copy()
    lib_dir = ccx_bin.parent.parent / "lib" / "x86_64-linux-gnu"
    if lib_dir.is_dir():
        env["LD_LIBRARY_PATH"] = f"{lib_dir}:{env.get('LD_LIBRARY_PATH', '')}"
    try:
        proc = subprocess.run(
            [str(ccx_bin), "-v"],
            capture_output=True, text=True, timeout=5, env=env,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
    except (subprocess.TimeoutExpired, OSError):
        return None
    m = re.search(r"Version\s*(\d+\.\d+(?:\.\d+)?)", out, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"\b(\d+\.\d+)\b", out)
    return m.group(1) if m else None


def _version_from_path(ccx_bin: Path) -> str | None:
    for piece in (ccx_bin.name, ccx_bin.parent.name, ccx_bin.parent.parent.name):
        m = re.search(r"(\d+\.\d+(?:\.\d+)?)", piece)
        if m:
            return m.group(1)
    return None


def _probe_ccx(ccx_bin: Path, source: str) -> SolverInstall | None:
    if not ccx_bin.is_file():
        return None
    version = _version_from_ccx(ccx_bin) or _version_from_path(ccx_bin) or "unknown"
    lib_dir = ccx_bin.parent.parent / "lib" / "x86_64-linux-gnu"
    extra = {"bin": str(ccx_bin)}
    if lib_dir.is_dir():
        extra["ld_library_path"] = str(lib_dir)
    return SolverInstall(
        name="calculix", version=version, path=str(ccx_bin.parent),
        source=source, extra=extra,
    )


def _candidates_from_env() -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    for var in ("CCX_BIN", "CALCULIX_HOME"):
        val = os.environ.get(var)
        if not val:
            continue
        p = Path(val)
        if p.is_file():
            out.append((p, f"env:{var}"))
        elif p.is_dir():
            for name in ("ccx", "ccx_2.20", "ccx_2.17", "ccx_2.11"):
                cand = p / "bin" / name
                if cand.is_file():
                    out.append((cand, f"env:{var}"))
    return out


def _candidates_from_sim_opt() -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    for base in [
        Path("/data/Chenyx/sim/opt/calculix/usr/bin"),
        Path("/opt/calculix/bin"),
        Path("/opt/calculix/usr/bin"),
        Path("/usr/local/bin"),
    ]:
        for name in ("ccx", "ccx_2.20", "ccx_2.17", "ccx_2.11", "CalculiX"):
            cand = base / name
            if cand.is_file():
                out.append((cand, f"default-path:{base}"))
    return out


def _candidates_from_path() -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    for name in ("ccx", "ccx_2.20", "ccx_2.17", "ccx_2.11"):
        found = shutil.which(name)
        if found:
            out.append((Path(found).resolve(), f"which:{name}"))
    return out


_INSTALL_FINDERS = [
    _candidates_from_env,
    _candidates_from_sim_opt,
    _candidates_from_path,
]


def _scan_calculix_installs() -> list[SolverInstall]:
    found: dict[str, SolverInstall] = {}
    for finder in _INSTALL_FINDERS:
        try:
            candidates = finder()
        except Exception:
            continue
        for ccx_bin, source in candidates:
            key = str(ccx_bin.resolve())
            if key in found:
                continue
            inst = _probe_ccx(ccx_bin, source)
            if inst is not None:
                found[key] = inst
    return sorted(found.values(), key=lambda i: i.version, reverse=True)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


class CalculixDriver:
    """Sim driver for CalculiX (CCX).

    DriverProtocol surface:
        name, detect, lint, connect, parse_output, run_file, detect_installed
    """

    @property
    def name(self) -> str:
        return "calculix"

    @property
    def supports_session(self) -> bool:
        return False

    def detect(self, script: Path) -> bool:
        try:
            if script.suffix.lower() != ".inp":
                return False
            text = script.read_text(encoding="utf-8", errors="replace")
            return bool(_INP_KEYWORD_RE.search(text))
        except (OSError, UnicodeDecodeError):
            return False

    def lint(self, script: Path) -> LintResult:
        diagnostics: list[Diagnostic] = []
        if script.suffix.lower() != ".inp":
            diagnostics.append(Diagnostic(
                level="error",
                message=f"Unsupported file type: {script.suffix} (expected .inp)",
            ))
            return LintResult(ok=False, diagnostics=diagnostics)

        try:
            text = script.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(level="error", message=f"Cannot read: {e}")],
            )

        if not _INP_KEYWORD_RE.search(text):
            diagnostics.append(Diagnostic(
                level="error",
                message="No CalculiX keywords found (expected *KEYWORD lines)",
            ))

        if not re.search(r"^\*STEP", text, re.MULTILINE | re.IGNORECASE):
            diagnostics.append(Diagnostic(
                level="warning",
                message="No *STEP keyword — deck may not define an analysis step",
            ))

        if not re.search(r"^\*MATERIAL", text, re.MULTILINE | re.IGNORECASE):
            diagnostics.append(Diagnostic(
                level="warning",
                message="No *MATERIAL keyword — deck may be incomplete",
            ))

        ok = not any(d.level == "error" for d in diagnostics)
        return LintResult(ok=ok, diagnostics=diagnostics)

    def connect(self) -> ConnectionInfo:
        installs = self.detect_installed()
        if not installs:
            return ConnectionInfo(
                solver="calculix", version=None, status="not_installed",
                message="No CalculiX (ccx) binary detected on this host",
            )
        top = installs[0]
        return ConnectionInfo(
            solver="calculix", version=top.version, status="ok",
            message=f"CalculiX {top.version} at {top.path}",
            solver_version=top.version,
        )

    def detect_installed(self) -> list[SolverInstall]:
        return _scan_calculix_installs()

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
            raise RuntimeError("CalculiX (ccx) is not installed on this host")

        if script.suffix.lower() != '.inp':
            raise RuntimeError(f'CalculiX only accepts .inp input decks (got {script.suffix})')

        top = installs[0]
        ccx_bin = top.extra.get("bin", "ccx")
        work_dir = script.parent
        jobname = script.stem

        env = os.environ.copy()
        ld_path = top.extra.get("ld_library_path")
        if ld_path:
            env["LD_LIBRARY_PATH"] = f"{ld_path}:{env.get('LD_LIBRARY_PATH', '')}"

        start = time.monotonic()
        try:
            proc = subprocess.run(
                [ccx_bin, jobname],
                capture_output=True, text=True,
                cwd=str(work_dir), env=env, timeout=600,
            )
        except subprocess.TimeoutExpired:
            return RunResult(
                exit_code=-1, stdout="", stderr="CalculiX run timed out after 600s",
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
