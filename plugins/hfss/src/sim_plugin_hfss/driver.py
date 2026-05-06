"""Ansys HFSS 3D driver for sim-cli.

The driver uses PyAEDT as the runtime control layer but keeps all PyAEDT imports
lazy. This lets ``sim check hfss`` and protocol tests run on machines that do
not have AEDT, HFSS, or PyAEDT importable.
"""
from __future__ import annotations

import ast
import glob
import io
import json
import os
import re
import shutil
import sys
import time
import traceback
import uuid
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sim.driver import ConnectionInfo, Diagnostic, LintResult, RunResult, SolverInstall
from sim.runner import run_subprocess


_HFSS_IMPORT_TEXT_RE = re.compile(
    r"^\s*(?:"
    r"from\s+ansys\.aedt\.core(?:\.hfss)?\s+import\s+.*\bHfss\b|"
    r"from\s+pyaedt\s+import\s+.*\bHfss\b|"
    r"import\s+pyaedt\b|"
    r"import\s+ansys\.aedt\.core(?:\.hfss)?\b"
    r")",
    re.MULTILINE,
)

_HFSS_CALL_TEXT_RE = re.compile(
    r"\b(?:Hfss|pyaedt\.Hfss|ansys\.aedt\.core\.Hfss)\s*\("
)

_AEDT_ENV_VARS = ("SIM_HFSS_AEDT_ROOT", "SIM_AEDT_ROOT")
_ANSYSEM_ENV_RE = re.compile(
    r"^(ANSYSEM_ROOT|ANSYSEMSV_ROOT|ANSYSEM_PY_CLIENT_ROOT)(\d{3})$",
    re.IGNORECASE,
)
_VERSION_CODE_RE = re.compile(r"v?(\d{3})", re.IGNORECASE)
_AEDT_EXECUTABLE_NAMES = ("ansysedt.exe", "ansysedt", "ansysedtsv.exe", "ansysedtsv")
_STUDENT_EXE_NAMES = ("ansysedtsv.exe", "ansysedtsv")
_DEFAULT_INSTALL_PATTERNS = [
    "C:/Program Files/AnsysEM/v*",
    "C:/Program Files/AnsysEM/v*/Win64",
    "C:/Program Files/ANSYS Inc/v*",
    "C:/Program Files/ANSYS Inc/v*/AnsysEM",
    "C:/Program Files/ANSYS Inc/v*/AnsysEM/Win64",
    "C:/Program Files/ANSYS Inc/ANSYS Student/v*",
    "C:/Program Files/ANSYS Inc/ANSYS Student/v*/AnsysEM",
    "D:/Program Files/AnsysEM/v*",
    "D:/Program Files/AnsysEM/v*/Win64",
    "D:/Program Files/ANSYS Inc/v*",
    "D:/Program Files/ANSYS Inc/v*/AnsysEM",
    "D:/Program Files/ANSYS Inc/v*/AnsysEM/Win64",
    "D:/Program Files/ANSYS Inc/ANSYS Student/v*",
    "D:/Program Files/ANSYS Inc/ANSYS Student/v*/AnsysEM",
    "/opt/ansys_inc/v*",
    "/opt/ansys_inc/v*/AnsysEM",
    "/opt/ansys_inc/v*/AnsysEM/Linux64",
    "/usr/ansys_inc/v*",
    "/usr/ansys_inc/v*/AnsysEM",
    "/usr/ansys_inc/v*/AnsysEM/Linux64",
    "/opt/AnsysEM/v*",
    "/opt/AnsysEM/v*/Linux64",
]

_NOT_INSTALLED_HINT = (
    "No Ansys Electronics Desktop installation detected on this host. "
    "Set SIM_HFSS_AEDT_ROOT or SIM_AEDT_ROOT to the AEDT root, or expose an "
    "AEDT launcher such as ansysedt or ansysedtsv on PATH."
)


@dataclass(frozen=True)
class _PyaedtApi:
    Desktop: Any | None
    Hfss: Any
    version: str | None


def _importlib_version(dist_name: str) -> str | None:
    try:
        from importlib.metadata import version

        return version(dist_name)
    except Exception:
        return None


def _try_import_pyaedt() -> _PyaedtApi | None:
    """Import PyAEDT lazily, supporting the modern and legacy import paths."""
    try:
        import ansys.aedt.core as core  # type: ignore

        Desktop = getattr(core, "Desktop", None)
        Hfss = getattr(core, "Hfss", None)
        if Hfss is None:
            from ansys.aedt.core.hfss import Hfss as HfssClass  # type: ignore

            Hfss = HfssClass
        return _PyaedtApi(
            Desktop=Desktop,
            Hfss=Hfss,
            version=getattr(core, "__version__", None) or _importlib_version("pyaedt"),
        )
    except Exception:
        pass

    try:
        import pyaedt  # type: ignore

        return _PyaedtApi(
            Desktop=getattr(pyaedt, "Desktop", None),
            Hfss=getattr(pyaedt, "Hfss"),
            version=getattr(pyaedt, "__version__", None) or _importlib_version("pyaedt"),
        )
    except Exception:
        return None


def _patch_pyaedt_student_startup_check() -> None:
    """Work around PyAEDT 0.26.x parsing ``2025.2SV`` as a float on Windows."""
    try:
        import ansys.aedt.core.desktop as desktop_mod  # type: ignore

        desktop_cls = desktop_mod.Desktop
        original = desktop_cls.check_starting_mode
        if getattr(original, "_sim_hfss_student_suffix_patch", False):
            return

        def patched_check_starting_mode(self):
            version_id = getattr(self, "aedt_version_id", "")
            if isinstance(version_id, str) and version_id.upper().endswith("SV"):
                trimmed = version_id[:-2]
                try:
                    self.aedt_version_id = trimmed
                    return original(self)
                finally:
                    self.aedt_version_id = version_id
            return original(self)

        patched_check_starting_mode._sim_hfss_student_suffix_patch = True
        desktop_cls.check_starting_mode = patched_check_starting_mode
    except Exception:
        return


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _has_hfss_signature(text: str) -> bool:
    """Return True when code appears to create or import a PyAEDT HFSS app."""
    if _HFSS_IMPORT_TEXT_RE.search(text) and _HFSS_CALL_TEXT_RE.search(text):
        return True

    try:
        tree = ast.parse(text)
    except SyntaxError:
        return bool(_HFSS_IMPORT_TEXT_RE.search(text) and "Hfss" in text)

    hfss_names: set[str] = set()
    module_aliases: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module in {"ansys.aedt.core", "ansys.aedt.core.hfss", "pyaedt"}:
                for alias in node.names:
                    if alias.name == "Hfss":
                        hfss_names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in {"pyaedt", "ansys.aedt.core", "ansys.aedt.core.hfss"}:
                    module_aliases.add(alias.asname or alias.name.split(".")[0])

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in hfss_names:
                return True
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "Hfss"
                and isinstance(func.value, ast.Name)
                and func.value.id in module_aliases
            ):
                return True

    return False


def _version_from_code(code: str | None) -> str | None:
    if not code or not code.isdigit() or len(code) != 3:
        return None
    return f"20{code[:2]}.{code[2]}"


def _code_from_version(version: str | None) -> str | None:
    if not version:
        return None
    m = re.match(r"^20(\d{2})\.(\d+)", version)
    if not m:
        return None
    return f"{m.group(1)}{m.group(2)}"


def _version_from_path(path: Path) -> str:
    for part in [path.name, *[p.name for p in path.parents[:3]]]:
        m = _VERSION_CODE_RE.search(part)
        if m:
            version = _version_from_code(m.group(1))
            if version:
                return version
        m = re.search(r"20(\d{2})[._ -]?R?([12])", part, re.IGNORECASE)
        if m:
            return f"20{m.group(1)}.{m.group(2)}"
    return "unknown"


def _find_aedt_executable(root: Path) -> Path | None:
    if root.is_file() and root.name.lower() in _AEDT_EXECUTABLE_NAMES:
        return root
    dirs = (
        root,
        root / "Win64",
        root / "Linux64",
        root / "AnsysEM",
        root / "AnsysEM" / "Win64",
        root / "AnsysEM" / "Linux64",
    )
    for directory in dirs:
        for name in _AEDT_EXECUTABLE_NAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
    return None


def _looks_like_student_install(root: Path, exe: Path) -> bool:
    values = [exe.name, str(root), str(exe)]
    return any("student" in value.lower() for value in values) or exe.name.lower() in _STUDENT_EXE_NAMES


def _install_from_root(
    root: Path,
    source: str,
    version: str | None = None,
    student_version: bool | None = None,
) -> SolverInstall | None:
    exe = _find_aedt_executable(root)
    if exe is None:
        return None
    install_root = exe.parent
    detected_version = version or _version_from_path(install_root)
    detected_student = _looks_like_student_install(root, exe)
    is_student = bool(student_version or detected_student)
    return SolverInstall(
        name="hfss",
        version=detected_version,
        path=str(install_root),
        source=source,
        extra={
            "executable": str(exe),
            "aedt_root": str(root),
            "student_version": is_student,
        },
    )


def _candidates_from_env() -> list[SolverInstall]:
    installs: list[SolverInstall] = []
    for var in _AEDT_ENV_VARS:
        value = os.environ.get(var)
        if value:
            install = _install_from_root(Path(value), f"env:{var}")
            if install:
                installs.append(install)

    for key, value in sorted(os.environ.items()):
        match = _ANSYSEM_ENV_RE.match(key)
        if not match or not value:
            continue
        install = _install_from_root(
            Path(value),
            f"env:{key}",
            version=_version_from_code(match.group(2)),
            student_version=match.group(1).upper() == "ANSYSEMSV_ROOT",
        )
        if install:
            installs.append(install)
    return installs


def _candidates_from_path() -> list[SolverInstall]:
    installs: list[SolverInstall] = []
    for executable in _AEDT_EXECUTABLE_NAMES:
        found = shutil.which(executable)
        if not found:
            continue
        path = Path(found).resolve()
        student_version = _looks_like_student_install(path.parent, path)
        installs.append(
            SolverInstall(
                name="hfss",
                version=_version_from_path(path),
                path=str(path.parent),
                source=f"which:{executable}",
                extra={
                    "executable": str(path),
                    "aedt_root": str(path.parent),
                    "student_version": student_version,
                },
            )
        )
    return installs


def _candidates_from_defaults() -> list[SolverInstall]:
    installs: list[SolverInstall] = []
    for pattern in _DEFAULT_INSTALL_PATTERNS:
        for raw in glob.glob(pattern):
            install = _install_from_root(Path(raw), f"default-path:{raw}")
            if install:
                installs.append(install)
    return installs


_INSTALL_FINDERS = [
    _candidates_from_env,
    _candidates_from_path,
    _candidates_from_defaults,
]


def _scan_aedt_installs() -> list[SolverInstall]:
    found: dict[str, SolverInstall] = {}
    for finder in _INSTALL_FINDERS:
        try:
            candidates = finder()
        except Exception:
            continue
        for install in candidates:
            exe = install.extra.get("executable") or install.path
            try:
                key = str(Path(exe).resolve())
            except OSError:
                key = str(exe)
            found.setdefault(key, install)
    return sorted(found.values(), key=_install_sort_key, reverse=True)


def _pyaedt_env_key(install: SolverInstall) -> str | None:
    code = _code_from_version(install.version)
    if not code:
        return None
    if install.extra.get("student_version"):
        return f"ANSYSEMSV_ROOT{code}"
    return f"ANSYSEM_ROOT{code}"


def _prepare_pyaedt_environment(install: SolverInstall | None) -> dict[str, str]:
    """Expose a detected install through the process env shape PyAEDT expects."""
    if install is None:
        return {}
    key = _pyaedt_env_key(install)
    if key is None:
        return {}
    os.environ[key] = install.path
    return {key: install.path}


def _install_sort_key(install: SolverInstall) -> tuple[int, int, str]:
    match = re.match(r"^(\d{4})\.(\d+)$", install.version)
    if match:
        return (1, int(match.group(1)) * 10 + int(match.group(2)), install.path)
    return (0, 0, install.path)


def _short_text(value: object, *, limit: int = 240) -> str:
    text = "" if value is None else str(value)
    text = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in text)
    return text[:limit]


def _safe_attr(obj: object, name: str, default: object = None) -> object:
    try:
        value = getattr(obj, name)
        return value() if callable(value) and name.startswith("get_") else value
    except Exception:
        return default


def _jsonable(value: object) -> object:
    try:
        json.dumps(value)
        return value
    except TypeError:
        return repr(value)


class HfssDriver:
    """Sim driver for Ansys HFSS 3D through PyAEDT."""

    def __init__(self) -> None:
        self._hfss: Any | None = None
        self._desktop: Any | None = None
        self._session_id: str | None = None
        self._ui_mode: str | None = None
        self._connected_at: str | None = None
        self._run_count: int = 0
        self._last_run: dict | None = None
        self._pyaedt_version: str | None = None
        self._launch_options: dict[str, object] = {}

    @property
    def name(self) -> str:
        return "hfss"

    @property
    def supports_session(self) -> bool:
        return True

    def detect(self, script: Path) -> bool:
        if script.suffix.lower() != ".py":
            return False
        text = _read_text(script)
        if text is None:
            return False
        return _has_hfss_signature(text)

    def lint(self, script: Path) -> LintResult:
        diagnostics: list[Diagnostic] = []
        if script.suffix.lower() != ".py":
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic("error", "HFSS v0.1.0 only lints PyAEDT Python scripts")],
            )

        text = _read_text(script)
        if text is None:
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic("error", f"cannot read file: {script}")],
            )

        try:
            ast.parse(text)
        except SyntaxError as e:
            diagnostics.append(Diagnostic("error", f"syntax error: {e}", e.lineno))

        if not _has_hfss_signature(text):
            diagnostics.append(
                Diagnostic(
                    "error",
                    "no PyAEDT HFSS construction found; expected ansys.aedt.core.hfss.Hfss or Hfss",
                )
            )

        ok = not any(d.level == "error" for d in diagnostics)
        return LintResult(ok=ok, diagnostics=diagnostics)

    def detect_installed(self) -> list[SolverInstall]:
        return _scan_aedt_installs()

    def connect(self) -> ConnectionInfo:
        installs = self.detect_installed()
        if not installs:
            return ConnectionInfo(
                solver=self.name,
                version=None,
                status="not_installed",
                message=_NOT_INSTALLED_HINT,
            )

        top = installs[0]
        _prepare_pyaedt_environment(top)
        api = _try_import_pyaedt()
        if api is None:
            return ConnectionInfo(
                solver=self.name,
                version=top.version,
                status="error",
                message=(
                    f"AEDT {top.version} was found, but PyAEDT is not importable. "
                    "Install with: uv pip install 'pyaedt>=0.26.3,<1'."
                ),
                solver_version=top.version,
            )

        return ConnectionInfo(
            solver=self.name,
            version=top.version,
            status="ok",
            message=f"AEDT {top.version} with PyAEDT {api.version or 'unknown'}",
            solver_version=top.version,
        )

    def parse_output(self, stdout: str) -> dict:
        if not stdout or not stdout.strip():
            return {}
        for line in reversed(stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        return {}

    def run_file(self, script: Path) -> RunResult:
        if script.suffix.lower() != ".py":
            raise RuntimeError(
                "HFSS v0.1.0 only runs PyAEDT Python scripts. Direct .aedt/.aedtz "
                "solve support is deferred until real HFSS validation is available."
            )
        return run_subprocess([sys.executable, str(script)], script=script, solver=self.name)

    def launch(
        self,
        *,
        ui_mode: str | None = "no_gui",
        mode: str | None = None,
        version: str | int | float | None = None,
        project: str | None = None,
        design: str | None = None,
        solution_type: str | None = None,
        setup: str | None = None,
        machine: str = "",
        port: int = 0,
        new_desktop: bool = True,
        close_on_exit: bool = False,
        student_version: bool | None = None,
        **kwargs: object,
    ) -> dict:
        installs = self.detect_installed()
        if not installs and not machine:
            return {
                "ok": False,
                "error_code": "SOLVER_NOT_INSTALLED",
                "message": _short_text(_NOT_INSTALLED_HINT),
            }

        selected_install = installs[0] if installs else None
        prepared_env = _prepare_pyaedt_environment(selected_install)
        api = _try_import_pyaedt()
        if api is None:
            return {
                "ok": False,
                "error_code": "RUN_FAILED",
                "message": "PyAEDT is not importable; install pyaedt>=0.26.3,<1.",
            }

        normalized_ui = (ui_mode or "no_gui").replace("-", "_").lower()
        if normalized_ui in {"no_gui", "nogui", "headless", "batch"}:
            non_graphical = True
            normalized_ui = "no_gui"
        elif normalized_ui in {"gui", "visible", "desktop"}:
            non_graphical = False
            normalized_ui = "gui"
        else:
            return {
                "ok": False,
                "error_code": "RUN_FAILED",
                "message": f"unsupported HFSS ui_mode: {ui_mode}",
            }

        if student_version is None:
            student_version = bool(selected_install and selected_install.extra.get("student_version"))
        if student_version:
            _patch_pyaedt_student_startup_check()

        launch_kwargs = {
            "project": project,
            "design": design,
            "solution_type": solution_type,
            "setup": setup,
            "version": version,
            "non_graphical": non_graphical,
            "new_desktop": new_desktop,
            "close_on_exit": close_on_exit,
            "student_version": student_version,
            "machine": machine,
            "port": port,
        }
        launch_kwargs = {k: v for k, v in launch_kwargs.items() if v not in {None, ""}}

        try:
            hfss = api.Hfss(**launch_kwargs)
        except Exception as e:
            return {
                "ok": False,
                "error_code": "RUN_FAILED",
                "message": _short_text(f"HFSS launch failed: {type(e).__name__}: {e}"),
                "details": {"traceback": traceback.format_exc(limit=5)},
            }

        self._hfss = hfss
        self._desktop = getattr(hfss, "desktop_class", None) or getattr(hfss, "desktop", None)
        self._session_id = f"hfss-{uuid.uuid4().hex[:12]}"
        self._ui_mode = normalized_ui
        self._connected_at = datetime.now(timezone.utc).isoformat()
        self._run_count = 0
        self._last_run = None
        self._pyaedt_version = api.version
        self._launch_options = {
            **launch_kwargs,
            "ui_mode": normalized_ui,
            "mode": mode,
            "prepared_env": prepared_env,
            **kwargs,
        }
        return {
            "ok": True,
            "session_id": self._session_id,
            "solver": self.name,
            "ui_mode": normalized_ui,
            "non_graphical": non_graphical,
            "student_version": student_version,
            "pyaedt_version": api.version,
            "launch_options": dict(self._launch_options),
        }

    def run(self, code: str, label: str = "") -> dict:
        if self._hfss is None:
            return {
                "ok": False,
                "error_code": "SESSION_NOT_FOUND",
                "message": "HFSS session is not launched.",
            }

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        start = time.monotonic()
        result: object = None
        ok = True
        error: str | None = None

        namespace = {
            "hfss": self._hfss,
            "desktop": self._desktop,
            "json": json,
        }
        try:
            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                result = self._execute_code(code, namespace)
        except Exception as e:
            ok = False
            error = f"{type(e).__name__}: {e}"
            stderr_buf.write(traceback.format_exc(limit=5))

        duration = round(time.monotonic() - start, 4)
        self._run_count += 1
        payload = {
            "ok": ok,
            "stdout": stdout_buf.getvalue(),
            "stderr": stderr_buf.getvalue(),
            "duration_s": duration,
            "label": label,
            "result": _jsonable(result),
        }
        if not ok:
            payload.update(
                {
                    "error_code": "RUN_FAILED",
                    "message": _short_text(error),
                }
            )
        self._last_run = payload
        return payload

    def query(self, name: str) -> dict:
        if name == "session.summary":
            return {
                "ok": True,
                "connected": self._hfss is not None,
                "session_id": self._session_id,
                "solver": self.name,
                "ui_mode": self._ui_mode,
                "run_count": self._run_count,
                "connected_at": self._connected_at,
                "pyaedt_version": self._pyaedt_version,
            }
        if name == "last.result":
            return {"ok": True, "result": self._last_run}
        if self._hfss is None:
            return {
                "ok": False,
                "error_code": "SESSION_NOT_FOUND",
                "message": "HFSS session is not launched.",
            }
        if name == "hfss.project.identity":
            return {"ok": True, **self._project_identity()}
        if name == "hfss.design.summary":
            return {"ok": True, **self._design_summary()}
        return {
            "ok": False,
            "error_code": "RUN_FAILED",
            "message": f"unknown HFSS query: {name}",
        }

    def disconnect(self) -> dict:
        if self._hfss is None:
            return {"ok": True, "disconnected": True}

        errors: list[str] = []
        try:
            release = getattr(self._hfss, "release_desktop", None)
            if callable(release):
                release(close_projects=False, close_desktop=True)
            elif self._desktop is not None:
                desktop_release = getattr(self._desktop, "release_desktop", None)
                if callable(desktop_release):
                    desktop_release(close_projects=False, close_desktop=True)
        except Exception as e:
            errors.append(f"{type(e).__name__}: {e}")
        finally:
            self._hfss = None
            self._desktop = None
            self._session_id = None

        if errors:
            return {
                "ok": False,
                "disconnected": True,
                "error_code": "RUN_FAILED",
                "message": _short_text("; ".join(errors)),
            }
        return {"ok": True, "disconnected": True}

    def _execute_code(self, code: str, namespace: dict[str, object]) -> object:
        tree = ast.parse(code, filename="<hfss-exec>", mode="exec")
        if tree.body and isinstance(tree.body[-1], ast.Expr):
            prefix = ast.Module(body=tree.body[:-1], type_ignores=[])
            ast.fix_missing_locations(prefix)
            exec(compile(prefix, "<hfss-exec>", "exec"), namespace)
            expr = ast.Expression(tree.body[-1].value)
            ast.fix_missing_locations(expr)
            return eval(compile(expr, "<hfss-exec>", "eval"), namespace)
        exec(compile(tree, "<hfss-exec>", "exec"), namespace)
        return namespace.get("result")

    def _project_identity(self) -> dict:
        hfss = self._hfss
        assert hfss is not None
        return {
            "project_name": _jsonable(_safe_attr(hfss, "project_name")),
            "project_file": _jsonable(_safe_attr(hfss, "project_file")),
            "project_path": _jsonable(_safe_attr(hfss, "project_path")),
            "working_directory": _jsonable(_safe_attr(hfss, "working_directory")),
            "aedt_version_id": _jsonable(_safe_attr(hfss, "aedt_version_id")),
        }

    def _design_summary(self) -> dict:
        hfss = self._hfss
        assert hfss is not None
        return {
            "design_name": _jsonable(_safe_attr(hfss, "design_name")),
            "design_type": _jsonable(_safe_attr(hfss, "design_type")),
            "solution_type": _jsonable(_safe_attr(hfss, "solution_type")),
            "setup_names": _jsonable(_safe_attr(hfss, "setup_names", [])),
            "excitation_names": _jsonable(_safe_attr(hfss, "excitation_names", [])),
            "valid_design": _jsonable(_safe_attr(hfss, "valid_design")),
        }
