"""PyBaMM driver for sim."""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

from sim.driver import ConnectionInfo, Diagnostic, LintResult
from sim.runner import run_subprocess


class PyBaMMLDriver:
    @property
    def name(self) -> str:
        return "pybamm"

    def detect(self, script: Path) -> bool:
        """Check if script imports pybamm."""
        text = script.read_text()
        return bool(re.search(r"^\s*(import pybamm|from pybamm\b)", text, re.MULTILINE))

    def lint(self, script: Path) -> LintResult:
        """Validate a PyBaMM script."""
        text = script.read_text()
        diagnostics: list[Diagnostic] = []

        # Check: pybamm imported?
        has_import = bool(
            re.search(r"^\s*(import pybamm|from pybamm\b)", text, re.MULTILINE)
        )
        if not has_import:
            # Check if pybamm is used without import
            if "pybamm" in text:
                diagnostics.append(
                    Diagnostic(
                        level="error",
                        message="Script uses pybamm but does not import it",
                    )
                )
            else:
                diagnostics.append(
                    Diagnostic(level="error", message="No pybamm import found")
                )

        # Check: syntax valid?
        try:
            ast.parse(text)
        except SyntaxError as e:
            diagnostics.append(
                Diagnostic(level="error", message=f"Syntax error: {e}", line=e.lineno)
            )

        # Check: .solve() called? (AST-based, ignores comments)
        if has_import:
            try:
                tree = ast.parse(text)
                has_solve = any(
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "solve"
                    for node in ast.walk(tree)
                )
                if not has_solve:
                    diagnostics.append(
                        Diagnostic(
                            level="warning",
                            message="No .solve() call found — script may not run a simulation",
                        )
                    )
            except SyntaxError:
                pass  # Already caught above

        ok = not any(d.level == "error" for d in diagnostics)
        return LintResult(ok=ok, diagnostics=diagnostics)

    def connect(self) -> ConnectionInfo:
        """Check if pybamm is importable and report version."""
        try:
            import pybamm

            return ConnectionInfo(
                solver="pybamm",
                version=pybamm.__version__,
                status="ok",
                message=f"pybamm {pybamm.__version__} available",
            )
        except ImportError:
            return ConnectionInfo(
                solver="pybamm",
                version=None,
                status="not_installed",
                message="pybamm is not installed in the current environment",
            )

    def parse_output(self, stdout: str) -> dict:
        """Parse structured JSON output from a PyBaMM script."""
        # Convention: script prints a JSON object (possibly among other output).
        # We take the last line that parses as JSON.
        for line in reversed(stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        return {}

    def run_file(self, script: Path):
        """Execute a PyBaMM Python script."""
        return run_subprocess(
            [sys.executable, str(script)],
            script=script,
            solver=self.name,
        )
