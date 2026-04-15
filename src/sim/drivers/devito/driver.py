"""Devito driver for sim.

Devito is a symbolic finite-difference DSL + just-in-time C compiler
(originally for seismic imaging at Imperial College). Pip-installable
(`pip install devito`); generates and compiles optimized C code at
runtime to evaluate stencils on multi-dim grids.

Scripts are plain `.py`:
    from devito import Grid, TimeFunction, Eq, solve, Operator
    grid = Grid(shape=(100, 100), extent=(1.0, 1.0))
    u = TimeFunction(name='u', grid=grid, time_order=1, space_order=2)
    eq = Eq(u.dt, 0.1*(u.dx2 + u.dy2))
    op = Operator([Eq(u.forward, solve(eq, u.forward))])
    op.apply(time_M=100, dt=0.001)
"""
from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from sim.driver import ConnectionInfo, Diagnostic, LintResult, SolverInstall
from sim.runner import run_subprocess


_IMPORT_RE = re.compile(r"^\s*(import\s+devito|from\s+devito\b)", re.MULTILINE)
_USAGE_RE = re.compile(
    r"\b(Grid|TimeFunction|Function|VectorTimeFunction|VectorFunction|"
    r"Eq|Operator|solve|Constant|SubDomain|SparseFunction|SparseTimeFunction)\b|"
    r"\.apply\(|\.dt\b|\.dx\b|\.dy\b|\.dz\b|\.dx2\b|\.dy2\b|\.dz2\b",
)


def _probe_python_for_devito(python_exe: Path) -> str | None:
    if not python_exe.is_file():
        return None
    try:
        proc = subprocess.run(
            [str(python_exe), "-c", "import devito; print(devito.__version__)"],
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    v = (proc.stdout or "").strip()
    return v or None


class DevitoDriver:
    """Sim driver for Devito (symbolic FD DSL + JIT C codegen)."""

    @property
    def name(self) -> str:
        return "devito"

    @property
    def supports_session(self) -> bool:
        return False

    def detect(self, script: Path) -> bool:
        try:
            if script.suffix.lower() != ".py":
                return False
            text = script.read_text(encoding="utf-8", errors="replace")
            return bool(_IMPORT_RE.search(text))
        except (OSError, UnicodeDecodeError):
            return False

    def lint(self, script: Path) -> LintResult:
        diagnostics: list[Diagnostic] = []
        if script.suffix.lower() != ".py":
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(
                    level="error",
                    message=f"Unsupported file type: {script.suffix} (expected .py)",
                )],
            )
        try:
            text = script.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(level="error", message=f"Cannot read: {e}")],
            )

        if not _IMPORT_RE.search(text):
            diagnostics.append(Diagnostic(
                level="error", message="No `import devito` / `from devito` found",
            ))

        try:
            ast.parse(text)
        except SyntaxError as e:
            diagnostics.append(Diagnostic(
                level="error", message=f"Syntax error: {e}", line=e.lineno,
            ))

        if _IMPORT_RE.search(text) and not _USAGE_RE.search(text):
            diagnostics.append(Diagnostic(
                level="warning",
                message=(
                    "No Grid / TimeFunction / Eq / Operator call — "
                    "script may not do anything"
                ),
            ))

        ok = not any(d.level == "error" for d in diagnostics)
        return LintResult(ok=ok, diagnostics=diagnostics)

    def connect(self) -> ConnectionInfo:
        installs = self.detect_installed()
        if not installs:
            return ConnectionInfo(
                solver="devito", version=None, status="not_installed",
                message="devito not importable from any known Python env",
            )
        top = installs[0]
        return ConnectionInfo(
            solver="devito", version=top.version, status="ok",
            message=f"Devito {top.version} in {top.path}",
            solver_version=top.version,
        )

    def detect_installed(self) -> list[SolverInstall]:
        found: dict[str, SolverInstall] = {}

        def _record(python: Path, source: str) -> None:
            ver = _probe_python_for_devito(python)
            if ver is None:
                return
            key = str(python.resolve())
            if key in found:
                return
            short = ".".join(ver.split(".")[:2])
            found[key] = SolverInstall(
                name="devito", version=short,
                path=str(python.parent), source=source,
                extra={"raw_version": ver, "python": str(python)},
            )

        _record(Path(sys.executable), "sys.executable")
        for name in ("python3", "python"):
            p = shutil.which(name)
            if p:
                _record(Path(p), f"which:{name}")
        return sorted(found.values(), key=lambda i: i.version, reverse=True)

    def parse_output(self, stdout: str) -> dict:
        for line in reversed(stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        return {}

    def run_file(self, script: Path):
        if script.suffix.lower() != ".py":
            raise RuntimeError(
                f"devito driver only accepts .py scripts (got {script.suffix})"
            )
        installs = self.detect_installed()
        if not installs:
            raise RuntimeError("Devito is not installed in any known Python env")
        python_exe = installs[0].extra.get("python", sys.executable)
        return run_subprocess(
            [python_exe, str(script)], script=script, solver=self.name,
        )
