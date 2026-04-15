"""Pyomo driver for sim.

Pyomo is a Python-based open-source modeling language for optimization
problems (LP/MIP/NLP/MINLP/SDP). Pip-installable (`pip install pyomo`);
pure Python frontend that dispatches to backend solvers
(GLPK, CBC, HiGHS, IPOPT, Gurobi, CPLEX, ...).

Scripts are plain `.py`:
    import pyomo.environ as pyo
    m = pyo.ConcreteModel()
    m.x = pyo.Var(within=pyo.NonNegativeReals)
    m.obj = pyo.Objective(expr=2*m.x, sense=pyo.minimize)
    m.c = pyo.Constraint(expr=m.x >= 1)
    pyo.SolverFactory('appsi_highs').solve(m)
    print(pyo.value(m.x))
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


_IMPORT_RE = re.compile(r"^\s*(import\s+pyomo|from\s+pyomo\b)", re.MULTILINE)
_USAGE_RE = re.compile(
    r"\b(pyo|pyomo)\.(ConcreteModel|AbstractModel|Var|Param|Set|"
    r"Objective|Constraint|RangeSet|SolverFactory|value|"
    r"NonNegativeReals|NonNegativeIntegers|Reals|Binary|Integers|"
    r"minimize|maximize)\b",
)


def _probe_python_for_pyomo(python_exe: Path) -> str | None:
    if not python_exe.is_file():
        return None
    try:
        proc = subprocess.run(
            [str(python_exe), "-c", "import pyomo; print(pyomo.__version__)"],
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    v = (proc.stdout or "").strip()
    return v or None


class PyomoDriver:
    """Sim driver for Pyomo (Python optimization modeling language)."""

    @property
    def name(self) -> str:
        return "pyomo"

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
                level="error",
                message="No `import pyomo` / `from pyomo` found",
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
                    "No ConcreteModel / Var / Objective / Constraint / "
                    "SolverFactory call — script may not do anything"
                ),
            ))

        ok = not any(d.level == "error" for d in diagnostics)
        return LintResult(ok=ok, diagnostics=diagnostics)

    def connect(self) -> ConnectionInfo:
        installs = self.detect_installed()
        if not installs:
            return ConnectionInfo(
                solver="pyomo", version=None, status="not_installed",
                message="pyomo not importable from any known Python env",
            )
        top = installs[0]
        return ConnectionInfo(
            solver="pyomo", version=top.version, status="ok",
            message=f"Pyomo {top.version} in {top.path}",
            solver_version=top.version,
        )

    def detect_installed(self) -> list[SolverInstall]:
        found: dict[str, SolverInstall] = {}

        def _record(python: Path, source: str) -> None:
            ver = _probe_python_for_pyomo(python)
            if ver is None:
                return
            key = str(python.resolve())
            if key in found:
                return
            short = ".".join(ver.split(".")[:2])
            found[key] = SolverInstall(
                name="pyomo", version=short,
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
                f"pyomo driver only accepts .py scripts (got {script.suffix})"
            )
        installs = self.detect_installed()
        if not installs:
            raise RuntimeError("Pyomo is not installed in any known Python env")
        python_exe = installs[0].extra.get("python", sys.executable)
        return run_subprocess(
            [python_exe, str(script)], script=script, solver=self.name,
        )
