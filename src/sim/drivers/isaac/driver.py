"""Isaac Sim driver for sim (v1: one-shot subprocess).

Isaac Sim is NVIDIA's Omniverse-Kit-based embodied-AI simulator.
Scripts must instantiate SimulationApp before any omni.* / isaacsim.*
imports. v1 is one-shot only; v2 will add persistent session support.
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from sim.driver import ConnectionInfo, Diagnostic, LintResult, RunResult, SolverInstall


_DETECT_RE = re.compile(
    r"(?:from\s+isaacsim\b|import\s+isaacsim\b"
    r"|from\s+omni\.(?:isaac|replicator|kit)\b"
    r"|SimulationApp\s*\()",
    re.MULTILINE,
)


def _probe_python(exe: Path) -> str | None:
    """Check if a Python interpreter has isaacsim installed.

    Uses importlib.metadata (no module import) to avoid triggering the
    Omniverse Kit bootstrap + EULA prompt.
    """
    try:
        if not exe or not Path(exe).is_file():
            return None
    except OSError:
        return None
    env = {**os.environ, "OMNI_KIT_ACCEPT_EULA": "YES"}
    try:
        proc = subprocess.run(
            [str(exe), "-c",
             "import importlib.metadata as m; print(m.version('isaacsim'))"],
            capture_output=True, text=True, timeout=10, env=env,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    return (proc.stdout or "").strip() or None


def _venv_python(venv: Path) -> Path | None:
    """Given a venv root, return its python executable."""
    win = venv / "Scripts" / "python.exe"
    unix = venv / "bin" / "python"
    if win.is_file():
        return win
    if unix.is_file():
        return unix
    return None


def _short_version(v: str) -> str:
    parts = v.split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else v


class IsaacDriver:
    @property
    def name(self) -> str:
        return "isaac"

    @property
    def supports_session(self) -> bool:
        return False

    def detect(self, script: Path) -> bool:
        try:
            if script.suffix.lower() != ".py":
                return False
            text = script.read_text(encoding="utf-8", errors="replace")
            return bool(_DETECT_RE.search(text))
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

        if not text.strip():
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(level="error", message="Script is empty")],
            )

        try:
            tree = ast.parse(text)
        except SyntaxError as e:
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(
                    level="error", message=f"Syntax error: {e}", line=e.lineno,
                )],
            )

        sim_app_line: int | None = None
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "SimulationApp"
            ):
                sim_app_line = node.lineno
                break

        if sim_app_line is None:
            diagnostics.append(Diagnostic(
                level="error",
                message=(
                    "No SimulationApp(...) instantiation found "
                    "— Isaac scripts must bootstrap via SimulationApp"
                ),
            ))

        if sim_app_line is not None:
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    if isinstance(node, ast.Import):
                        names = [n.name for n in node.names]
                    else:
                        names = [node.module or ""]
                    for n in names:
                        if (
                            n and (n.startswith("omni.") or n.startswith("isaacsim"))
                            and n != "isaacsim"
                        ):
                            if node.lineno < sim_app_line:
                                diagnostics.append(Diagnostic(
                                    level="warning",
                                    message=(
                                        f"Import '{n}' at line {node.lineno} precedes "
                                        f"SimulationApp() at line {sim_app_line} "
                                        "— Isaac hard-fails at runtime"
                                    ),
                                    line=node.lineno,
                                ))
                                break

        has_close_call = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "close"
            for node in ast.walk(tree)
        )
        if sim_app_line is not None and not has_close_call:
            diagnostics.append(Diagnostic(
                level="warning",
                message="No simulation_app.close() call — process may hang on exit",
            ))

        ok = not any(d.level == "error" for d in diagnostics)
        return LintResult(ok=ok, diagnostics=diagnostics)

    def detect_installed(self) -> list[SolverInstall]:
        found: dict[str, SolverInstall] = {}

        def _record(exe: Path, version: str, source: str, path_root: str) -> None:
            try:
                key = str(Path(exe).resolve())
            except OSError:
                key = str(exe)
            if key in found:
                return
            found[key] = SolverInstall(
                name="isaac", version=_short_version(version),
                path=path_root, source=source,
                extra={"python": str(exe), "raw_version": version},
            )

        env_py = os.environ.get("ISAAC_PYTHON")
        if env_py:
            ver = _probe_python(Path(env_py))
            if ver:
                _record(Path(env_py), ver, "env:ISAAC_PYTHON",
                        str(Path(env_py).parent))

        env_venv = os.environ.get("ISAAC_VENV")
        if env_venv:
            py = _venv_python(Path(env_venv))
            if py:
                ver = _probe_python(py)
                if ver:
                    _record(py, ver, "env:ISAAC_VENV", str(env_venv))

        ver = _probe_python(Path(sys.executable))
        if ver:
            _record(Path(sys.executable), ver, "sys.executable",
                    str(Path(sys.executable).parent))

        return sorted(found.values(), key=lambda i: i.version, reverse=True)

    def connect(self) -> ConnectionInfo:
        installs = self.detect_installed()
        if not installs:
            return ConnectionInfo(
                solver="isaac", version=None, status="not_installed",
                message=(
                    "Isaac Sim not found. Install with: "
                    "uv venv <path> --python 3.10 && "
                    "uv pip install --python <path>/Scripts/python.exe "
                    "\"isaacsim[all]\" --extra-index-url https://pypi.nvidia.com ; "
                    "then setx ISAAC_VENV <path>"
                ),
            )
        top = installs[0]
        raw = top.extra.get("raw_version", top.version)
        return ConnectionInfo(
            solver="isaac", version=top.version, status="ok",
            message=f"Isaac Sim {raw} at {top.path}",
            solver_version=raw,
        )

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
        if script.suffix.lower() != ".py":
            raise RuntimeError(
                f"Isaac driver only accepts .py scripts (got {script.suffix})"
            )
        installs = self.detect_installed()
        if not installs:
            raise RuntimeError(
                "Isaac Sim is not installed. Install with: "
                "uv venv <path> --python 3.10 && "
                "uv pip install --python <path>/Scripts/python.exe "
                "\"isaacsim[all]\" --extra-index-url https://pypi.nvidia.com ; "
                "then setx ISAAC_VENV <path>"
            )
        isaac_py = installs[0].extra["python"]
        env = {**os.environ, "OMNI_KIT_ACCEPT_EULA": "YES"}
        cmd = [str(isaac_py), str(script)]

        start = time.monotonic()
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                env=env, timeout=600,
            )
        except subprocess.TimeoutExpired:
            duration = time.monotonic() - start
            return RunResult(
                exit_code=-1, stdout="",
                stderr="Isaac Sim execution timed out after 600s",
                duration_s=round(duration, 3),
                script=str(script), solver=self.name,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        duration = time.monotonic() - start
        return RunResult(
            exit_code=proc.returncode,
            stdout=(proc.stdout or "").strip(),
            stderr=(proc.stderr or "").strip(),
            duration_s=round(duration, 3),
            script=str(script), solver=self.name,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
