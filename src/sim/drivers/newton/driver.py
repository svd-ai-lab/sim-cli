"""Newton driver for sim (v1: one-shot subprocess).

NVIDIA Newton is a GPU physics engine built on Warp, distinct from Isaac Sim.
Scripts can be either:
  - recipe JSON  ({"schema":"newton-cli/recipe/v1"|"sim/newton/recipe/v1", ...})
  - Python .py   (run-script B-route: artifact dir + envelope on stdout)

Warp/CUDA is never imported in sim's main process — all execution happens in
a subprocess launched with a Python that has `newton` + `warp-lang` installed.
Interpreter resolution: NEWTON_PYTHON → NEWTON_VENV/<bin>/python → sys.executable.
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from sim.driver import ConnectionInfo, Diagnostic, LintResult, RunResult, SolverInstall


_PY_DETECT_RE = re.compile(
    r"(?:^\s*(?:from|import)\s+(?:newton|warp)\b"
    r"|@wp\.kernel\b"
    r"|\bSolver(?:XPBD|VBD|MuJoCo|ImplicitMPM|Style3D|SemiImplicit)\b)",
    re.MULTILINE,
)

_RECIPE_SCHEMAS = {"newton-cli/recipe/v1", "sim/newton/recipe/v1"}

_ENVELOPE_RE = re.compile(r'^\{"schema":\s*"sim/newton/v1"')


def _probe_python(exe: Path) -> tuple[str, str] | None:
    """Check if a Python has both `newton` and `warp-lang` installed.

    Returns (newton_version, warp_version) or None. Uses importlib.metadata
    so no heavy imports happen (avoids CUDA init during probing).
    """
    try:
        if not exe or not Path(exe).is_file():
            return None
    except OSError:
        return None
    try:
        proc = subprocess.run(
            [str(exe), "-c",
             "import importlib.metadata as m;"
             "print(m.version('newton'));"
             "print(m.version('warp-lang'))"],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
    if len(lines) < 2:
        return None
    return lines[0], lines[1]


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


class NewtonDriver:
    @property
    def name(self) -> str:
        return "newton"

    @property
    def supports_session(self) -> bool:
        return False

    # ------------------------------------------------------------------ detect
    def detect(self, script: Path) -> bool:
        try:
            if script.suffix.lower() == ".json":
                text = script.read_text(encoding="utf-8", errors="replace")
                try:
                    obj = json.loads(text)
                except json.JSONDecodeError:
                    return False
                schema = obj.get("schema") if isinstance(obj, dict) else None
                return isinstance(schema, str) and schema in _RECIPE_SCHEMAS
            if script.suffix.lower() == ".py":
                text = script.read_text(encoding="utf-8", errors="replace")
                return bool(_PY_DETECT_RE.search(text))
            return False
        except (OSError, UnicodeDecodeError):
            return False

    # -------------------------------------------------------------------- lint
    def lint(self, script: Path) -> LintResult:
        suffix = script.suffix.lower()
        if suffix not in (".py", ".json"):
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(
                    level="error",
                    message=f"Unsupported file type: {script.suffix} (expected .py or .json)",
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

        if suffix == ".json":
            return self._lint_recipe(text)
        return self._lint_py(text)

    def _lint_recipe(self, text: str) -> LintResult:
        diags: list[Diagnostic] = []
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as e:
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(
                    level="error", message=f"Invalid JSON: {e}", line=e.lineno,
                )],
            )
        if not isinstance(obj, dict):
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(level="error", message="Recipe must be a JSON object")],
            )
        schema = obj.get("schema")
        if schema not in _RECIPE_SCHEMAS:
            diags.append(Diagnostic(
                level="error",
                message=(
                    f"Unknown recipe schema: {schema!r} "
                    f"(expected one of {sorted(_RECIPE_SCHEMAS)})"
                ),
            ))
        ops = obj.get("ops")
        if not isinstance(ops, list):
            diags.append(Diagnostic(level="error", message="Recipe missing 'ops' list"))
        else:
            for i, op in enumerate(ops):
                if not isinstance(op, dict):
                    diags.append(Diagnostic(
                        level="error", message=f"ops[{i}] is not an object"))
                    continue
                if not isinstance(op.get("op"), str):
                    diags.append(Diagnostic(
                        level="error", message=f"ops[{i}] missing 'op' string"))
                if "args" in op and not isinstance(op["args"], dict):
                    diags.append(Diagnostic(
                        level="error", message=f"ops[{i}].args must be an object"))
        ok = not any(d.level == "error" for d in diags)
        return LintResult(ok=ok, diagnostics=diags)

    def _lint_py(self, text: str) -> LintResult:
        diags: list[Diagnostic] = []
        try:
            tree = ast.parse(text)
        except SyntaxError as e:
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(
                    level="error", message=f"Syntax error: {e}", line=e.lineno,
                )],
            )
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = (
                    [n.name for n in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                )
                for n in names:
                    if n and n.startswith("newton._src"):
                        diags.append(Diagnostic(
                            level="warning",
                            message=(
                                f"Import '{n}' uses private module 'newton._src' — "
                                "only public modules (newton, newton.geometry, "
                                "newton.solvers, ...) are supported"
                            ),
                            line=node.lineno,
                        ))
        ok = not any(d.level == "error" for d in diags)
        return LintResult(ok=ok, diagnostics=diags)

    # ------------------------------------------------------- detect_installed
    def detect_installed(self) -> list[SolverInstall]:
        found: dict[str, SolverInstall] = {}

        def _record(exe: Path, ver_n: str, ver_w: str, source: str, root: str) -> None:
            try:
                key = str(Path(exe).resolve())
            except OSError:
                key = str(exe)
            if key in found:
                return
            found[key] = SolverInstall(
                name="newton",
                version=_short_version(ver_n),
                path=root,
                source=source,
                extra={
                    "python": str(exe),
                    "raw_version": ver_n,
                    "warp_version": ver_w,
                },
            )

        env_py = os.environ.get("NEWTON_PYTHON")
        if env_py:
            probe = _probe_python(Path(env_py))
            if probe:
                _record(Path(env_py), probe[0], probe[1],
                        "env:NEWTON_PYTHON", str(Path(env_py).parent))

        env_venv = os.environ.get("NEWTON_VENV")
        if env_venv:
            py = _venv_python(Path(env_venv))
            if py:
                probe = _probe_python(py)
                if probe:
                    _record(py, probe[0], probe[1],
                            "env:NEWTON_VENV", str(env_venv))

        probe = _probe_python(Path(sys.executable))
        if probe:
            _record(Path(sys.executable), probe[0], probe[1],
                    "sys.executable", str(Path(sys.executable).parent))

        return sorted(found.values(), key=lambda i: i.version, reverse=True)

    # ----------------------------------------------------------------- connect
    def connect(self) -> ConnectionInfo:
        installs = self.detect_installed()
        if not installs:
            return ConnectionInfo(
                solver="newton", version=None, status="not_installed",
                message=(
                    "Newton not found. Install with: "
                    "uv venv <path> --python 3.12 && "
                    "uv pip install --python <path>/Scripts/python.exe warp-lang newton ; "
                    "then setx NEWTON_VENV <path>"
                ),
            )
        top = installs[0]
        raw_n = top.extra.get("raw_version", top.version)
        raw_w = top.extra.get("warp_version", "?")
        return ConnectionInfo(
            solver="newton", version=top.version, status="ok",
            message=f"Newton {raw_n} (warp {raw_w}) at {top.path}",
            solver_version=raw_n,
        )

    # ----------------------------------------------------------- parse_output
    def parse_output(self, stdout: str) -> dict:
        for line in reversed(stdout.strip().splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            if not _ENVELOPE_RE.search(line):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            data = obj.get("data") if isinstance(obj, dict) else None
            if isinstance(data, dict):
                return data
        return {}

    # -------------------------------------------------------------- run_file
    def run_file(self, script: Path) -> RunResult:
        suffix = script.suffix.lower()
        if suffix not in (".py", ".json"):
            raise RuntimeError(
                f"Newton driver only accepts .py or .json scripts (got {script.suffix})"
            )
        installs = self.detect_installed()
        if not installs:
            raise RuntimeError(
                "Newton is not installed. Install with: "
                "uv venv <path> --python 3.12 && "
                "uv pip install --python <path>/Scripts/python.exe warp-lang newton ; "
                "then setx NEWTON_VENV <path>"
            )
        newton_py = installs[0].extra["python"]

        artifact_dir = Path(tempfile.mkdtemp(prefix="sim_newton_"))
        env = {
            **os.environ,
            "SIM_ARTIFACT_DIR": str(artifact_dir),
            "NEWTON_CLI_ARTIFACT_DIR": str(artifact_dir),
        }
        # Invoke _entry.py by file path (not `-m sim.drivers.newton._entry`)
        # so the newton venv doesn't import `sim.drivers/__init__.py` and drag
        # in unrelated driver deps (httpx, comsol, ...). The entry inserts its
        # own dir into sys.path to load sibling modules.
        entry_path = Path(__file__).resolve().parent / "_entry.py"
        cmd = [str(newton_py), str(entry_path), str(script.resolve())]

        start = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=600,
                cwd=str(Path(script).resolve().parent),
            )
        except subprocess.TimeoutExpired:
            duration = time.monotonic() - start
            return RunResult(
                exit_code=-1, stdout="",
                stderr="Newton execution timed out after 600s",
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

    # Session lifecycle stubs — one-shot driver, but DriverProtocol is
    # runtime_checkable so every method must exist. See `sim.driver`.
    def launch(self, **kwargs) -> dict:
        raise NotImplementedError(f"{self.name} driver does not support sessions")

    def run(self, code: str, label: str = "") -> dict:
        raise NotImplementedError(f"{self.name} driver does not support sessions")

    def disconnect(self) -> dict:
        return {"ok": True, "disconnected": True}
