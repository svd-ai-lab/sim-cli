"""Ansys HFSS 3D driver for sim-cli.

The driver uses PyAEDT as the runtime control layer but keeps all PyAEDT imports
lazy. This lets ``sim check hfss`` and protocol tests run on machines that do
not have AEDT, HFSS, or PyAEDT importable.
"""
from __future__ import annotations

import ast
import csv
import glob
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
import uuid
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sim._timeout import call_with_timeout
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
_DEFAULT_EXEC_TIMEOUT_S = 300.0
_HFSS_SOLVE_TEXT_RE = re.compile(
    r"\b(?:analyze(?:_setup|_all)?|solve(?:_setup)?|run_sweep)\s*\(",
    re.IGNORECASE,
)
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


def _coerce_timeout_s(value: object, *, source: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid HFSS exec timeout from {source}: {value!r}") from exc


def _looks_like_solve_snippet(code: str) -> bool:
    return bool(_HFSS_SOLVE_TEXT_RE.search(code))


def _pid_from_value(value: object) -> int | None:
    try:
        pid = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def _runtime_aedt_pid(*objects: object) -> int | None:
    seen: set[int] = set()
    for obj in objects:
        if obj is None or id(obj) in seen:
            continue
        seen.add(id(obj))
        for name in (
            "aedt_process_id",
            "aedt_process_pid",
            "process_id",
            "processid",
            "pid",
        ):
            pid = _pid_from_value(_safe_attr(obj, name))
            if pid is not None:
                return pid
        for name in ("GetProcessID", "get_process_id", "get_pid"):
            pid = _pid_from_value(_safe_call(obj, name))
            if pid is not None:
                return pid
    return None


def _aedt_process_pids() -> set[int]:
    names = {name.lower() for name in _AEDT_EXECUTABLE_NAMES}
    if os.name == "nt":
        try:
            proc = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except OSError:
            return set()
        if proc.returncode != 0:
            return set()
        pids: set[int] = set()
        for row in csv.reader(proc.stdout.splitlines()):
            if len(row) < 2:
                continue
            if row[0].strip().lower() not in names:
                continue
            pid = _pid_from_value(row[1].strip())
            if pid is not None:
                pids.add(pid)
        return pids

    try:
        proc = subprocess.run(
            ["ps", "-eo", "pid=,comm="],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:
        return set()
    if proc.returncode != 0:
        return set()
    pids: set[int] = set()
    for line in proc.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        if parts[1].strip().lower() not in names:
            continue
        pid = _pid_from_value(parts[0])
        if pid is not None:
            pids.add(pid)
    return pids


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        return pid in _aedt_process_pids()
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _kill_pid(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            proc = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except OSError:
            return False
        return proc.returncode == 0
    try:
        os.kill(pid, 9)
        return True
    except OSError:
        return False


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


def _safe_call(obj: object, name: str, *args: object, default: object = None) -> object:
    try:
        fn = getattr(obj, name)
        if callable(fn):
            return fn(*args)
    except Exception:
        return default
    return default


def _as_list(value: object) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple | set):
        return list(value)
    if isinstance(value, dict):
        return list(value.values())
    return [value]


def _name_of(value: object) -> str:
    return str(_safe_attr(value, "name") or _safe_attr(value, "Name") or value)


def _parse_message(raw: object) -> dict:
    text = str(raw)
    lowered = text.lower()
    if "error" in lowered or "fail" in lowered:
        severity = "error"
    elif "warning" in lowered or "warn" in lowered:
        severity = "warning"
    elif "info" in lowered:
        severity = "info"
    else:
        severity = "unknown"

    objects: list[str] = []
    for match in re.finditer(r"\bParts?\s+([^,\s]+)\s+and\s+([^,\s]+)", text, re.IGNORECASE):
        objects.extend([match.group(1), match.group(2)])
    for match in re.finditer(r"\b(?:object|part|port|boundary)\s+'([^']+)'", text, re.IGNORECASE):
        objects.append(match.group(1))

    return {
        "severity": severity,
        "text": text,
        "objects": sorted(set(objects)),
    }


def _read_su_file(path: Path) -> dict | None:
    text = _read_text(path)
    if text is None:
        return None
    fields: dict[str, object] = {"path": str(path)}
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        key, value = parts[0], parts[1]
        if key in {"Frequency", "Success", "NumTets", "MatrixSize", "TotalModes"}:
            try:
                numeric = float(value)
                fields[key] = int(numeric) if numeric.is_integer() else numeric
            except ValueError:
                fields[key] = value
    frequency_hz = fields.get("Frequency")
    if isinstance(frequency_hz, int | float):
        fields["frequency_ghz"] = float(frequency_hz) / 1e9
    success = fields.get("Success")
    if isinstance(success, int | float):
        fields["success"] = bool(success)
    return fields


def _touchstone_labels(nports: int) -> list[str]:
    if nports <= 0:
        return ["S(1,1)"]
    labels: list[str] = []
    for col in range(1, nports + 1):
        for row in range(1, nports + 1):
            labels.append(f"S({row},{col})")
    return labels


def touchstone_summary(
    path: str | os.PathLike[str],
    *,
    target_frequencies_ghz: list[float] | tuple[float, ...] | None = None,
    threshold_db: float = -10.0,
    parameter: str = "S(1,1)",
) -> dict:
    """Parse a Touchstone file for lightweight S-parameter acceptance metrics."""
    file_path = Path(path)
    if not file_path.is_file():
        return {
            "ok": False,
            "available": False,
            "error_code": "FILE_NOT_FOUND",
            "message": f"Touchstone file not found: {file_path}",
            "path": str(file_path),
        }

    unit_scale_to_ghz = {"hz": 1e-9, "khz": 1e-6, "mhz": 1e-3, "ghz": 1.0}
    unit = "ghz"
    fmt = "ma"
    match = re.search(r"\.s(\d+)p$", file_path.name, re.IGNORECASE)
    nports = int(match.group(1)) if match else 1
    labels = _touchstone_labels(nports)
    if parameter not in labels:
        return {
            "ok": False,
            "available": True,
            "error_code": "PARAMETER_NOT_FOUND",
            "message": f"{parameter} not present in inferred {nports}-port Touchstone data.",
            "path": str(file_path),
            "s_parameters": labels,
        }
    pair_index = labels.index(parameter)
    required_values = 1 + 2 * len(labels)

    rows: list[dict[str, float]] = []
    for raw_line in file_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("!"):
            continue
        if line.startswith("#"):
            parts = line[1:].lower().split()
            if parts:
                unit = parts[0]
            if "db" in parts:
                fmt = "db"
            elif "ri" in parts:
                fmt = "ri"
            else:
                fmt = "ma"
            continue
        values = line.split()
        if len(values) < required_values:
            continue
        try:
            freq_ghz = float(values[0]) * unit_scale_to_ghz.get(unit, 1.0)
            first = float(values[1 + 2 * pair_index])
            second = float(values[2 + 2 * pair_index])
        except ValueError:
            continue

        if fmt == "db":
            mag_db = first
            mag = 10 ** (mag_db / 20.0)
            angle_deg = second
        elif fmt == "ri":
            mag = math.hypot(first, second)
            mag_db = 20.0 * math.log10(max(mag, 1e-300))
            angle_deg = math.degrees(math.atan2(second, first))
        else:
            mag = first
            mag_db = 20.0 * math.log10(max(mag, 1e-300))
            angle_deg = second
        rows.append({
            "frequency_ghz": freq_ghz,
            "magnitude": mag,
            "angle_deg": angle_deg,
            "db": mag_db,
        })

    if not rows:
        return {
            "ok": False,
            "available": True,
            "error_code": "NO_DATA",
            "message": f"No {parameter} rows found in Touchstone file.",
            "path": str(file_path),
            "format": fmt,
            "frequency_unit": unit,
            "s_parameters": labels,
        }

    min_row = min(rows, key=lambda row: row["db"])
    below_threshold = [row for row in rows if row["db"] <= threshold_db]
    targets = []
    for target in target_frequencies_ghz or []:
        nearest = min(rows, key=lambda row: abs(row["frequency_ghz"] - float(target)))
        targets.append({"target_ghz": float(target), **nearest})

    return {
        "ok": True,
        "available": True,
        "path": str(file_path),
        "parameter": parameter,
        "format": fmt,
        "frequency_unit": unit,
        "row_count": len(rows),
        "s_parameters": labels,
        "min": min_row,
        "targets": targets,
        "threshold_db": threshold_db,
        "threshold_bandwidth_ghz": (
            [min(row["frequency_ghz"] for row in below_threshold), max(row["frequency_ghz"] for row in below_threshold)]
            if below_threshold else None
        ),
    }


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
        self._last_timeout: dict | None = None
        self._last_cleanup: dict | None = None
        self._pyaedt_version: str | None = None
        self._launch_options: dict[str, object] = {}
        self._owned_aedt_pids: set[int] = set()

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
                diagnostics=[Diagnostic("error", "HFSS v0.1.1 only lints PyAEDT Python scripts")],
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
                "HFSS v0.1.1 only runs PyAEDT Python scripts. Direct .aedt/.aedtz "
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
        owns_aedt_process = self._should_own_aedt_process(
            new_desktop=new_desktop,
            machine=machine,
            port=port,
        )
        before_aedt_pids = _aedt_process_pids() if owns_aedt_process else set()

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
        runtime_pid = _runtime_aedt_pid(
            hfss,
            self._desktop,
            _safe_attr(hfss, "odesktop"),
        )
        after_aedt_pids = _aedt_process_pids() if owns_aedt_process else set()
        self._owned_aedt_pids = self._identify_owned_aedt_pids(
            owns_process=owns_aedt_process,
            before_pids=before_aedt_pids,
            after_pids=after_aedt_pids,
            runtime_pid=runtime_pid,
        )
        self._session_id = f"hfss-{uuid.uuid4().hex[:12]}"
        self._ui_mode = normalized_ui
        self._connected_at = datetime.now(timezone.utc).isoformat()
        self._run_count = 0
        self._last_run = None
        self._last_timeout = None
        self._last_cleanup = None
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
            "aedt_pid": runtime_pid,
            "owned_aedt_pids": sorted(self._owned_aedt_pids),
            "launch_options": dict(self._launch_options),
        }

    def run(self, code: str, label: str = "", timeout_s: float | None = None) -> dict:
        if self._hfss is None:
            return {
                "ok": False,
                "error_code": "SESSION_NOT_FOUND",
                "message": "HFSS session is not launched.",
            }

        try:
            timeout_budget, timeout_source = self._resolve_exec_timeout(code, timeout_s)
        except ValueError as e:
            return {
                "ok": False,
                "stdout": "",
                "stderr": "",
                "duration_s": 0,
                "label": label,
                "result": None,
                "error_code": "RUN_FAILED",
                "message": _short_text(e),
            }

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        start = time.monotonic()
        result: object = None
        ok = True
        error: str | None = None
        hung = False
        cleanup: dict | None = None

        namespace = {
            "hfss": self._hfss,
            "desktop": self._desktop,
            "json": json,
            "touchstone_summary": touchstone_summary,
        }

        def _run_snippet() -> object:
            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                return self._execute_code(code, namespace)

        timed = call_with_timeout(_run_snippet, timeout_s=timeout_budget)
        if timed.hung:
            ok = False
            hung = True
            error = f"HFSS snippet exceeded timeout_s={timeout_budget}"
            self._last_timeout = {
                "label": label,
                "timeout_s": timeout_budget,
                "timeout_source": timeout_source,
                "elapsed_s": round(timed.elapsed_s, 4),
            }
            cleanup = self._cleanup_session(reason="timeout")
        elif timed.exception is not None:
            ok = False
            exc = timed.exception
            error = f"{type(exc).__name__}: {exc}"
            stderr_buf.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__, limit=5)))
        else:
            result = timed.value

        duration = round(time.monotonic() - start, 4)
        self._run_count += 1
        payload = {
            "ok": ok,
            "stdout": stdout_buf.getvalue(),
            "stderr": stderr_buf.getvalue(),
            "duration_s": duration,
            "label": label,
            "result": _jsonable(result),
            "timeout": {
                "enabled": bool(timeout_budget and timeout_budget > 0),
                "timeout_s": timeout_budget,
                "source": timeout_source,
            },
        }
        if not ok:
            payload.update(
                {
                    "hung": hung,
                    "error_code": "RUN_FAILED",
                    "message": _short_text(error),
                }
            )
        if cleanup is not None:
            payload["cleanup"] = cleanup
        self._last_run = payload
        return payload

    def query(self, name: str) -> dict:
        if name in {"health", "session.health"}:
            return self.health()
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
        if name == "hfss.model.summary":
            return {"ok": True, **self._model_summary()}
        if name == "hfss.boundaries.summary":
            return {"ok": True, **self._boundaries_summary()}
        if name == "hfss.setups.summary":
            return {"ok": True, **self._setups_summary()}
        if name == "hfss.messages":
            return {"ok": True, **self._messages_summary()}
        if name == "hfss.solution.progress":
            return {"ok": True, **self._solution_progress()}
        return {
            "ok": False,
            "error_code": "RUN_FAILED",
            "message": f"unknown HFSS query: {name}",
        }

    def disconnect(self) -> dict:
        if self._hfss is None and not self._owned_aedt_pids:
            return {"ok": True, "disconnected": True}

        cleanup = self._cleanup_session(reason="disconnect")
        errors = cleanup.get("release_errors") or []

        if errors:
            return {
                "ok": False,
                "disconnected": True,
                "error_code": "RUN_FAILED",
                "message": _short_text("; ".join(errors)),
                "cleanup": cleanup,
            }
        return {"ok": True, "disconnected": True, "cleanup": cleanup}

    def health(self) -> dict:
        if self._hfss is None:
            return {
                "ok": False,
                "connected": False,
                "code": "hfss.session.disconnected",
                "message": "No active HFSS session is launched.",
                "session_id": self._session_id,
                "solver": self.name,
                "ui_mode": self._ui_mode,
                "pyaedt_version": self._pyaedt_version,
                "owned_aedt_pids": sorted(self._owned_aedt_pids),
                "last_timeout": self._last_timeout,
                "last_cleanup": self._last_cleanup,
            }

        pid_status = {
            str(pid): _pid_is_alive(pid)
            for pid in sorted(self._owned_aedt_pids)
        }
        owned_pid_dead = bool(pid_status) and not any(pid_status.values())
        connected = not owned_pid_dead
        code = "hfss.session.connected" if connected else "hfss.aedt.process_exited"
        message = "HFSS session is connected" if connected else "Tracked AEDT process is not alive"

        project = self._safe_health_call(self._project_identity)
        design = self._safe_health_call(self._design_summary)
        messages = self._safe_health_call(self._messages_summary)
        progress = self._safe_health_call(self._solution_progress)

        return {
            "ok": connected,
            "connected": connected,
            "code": code,
            "message": message,
            "session_id": self._session_id,
            "solver": self.name,
            "ui_mode": self._ui_mode,
            "run_count": self._run_count,
            "connected_at": self._connected_at,
            "pyaedt_version": self._pyaedt_version,
            "launch_options": dict(self._launch_options),
            "owned_aedt_pids": sorted(self._owned_aedt_pids),
            "owned_aedt_pid_alive": pid_status,
            "project": project,
            "design": design,
            "messages": messages,
            "solution_progress": progress,
            "last_run": self._last_run,
            "last_timeout": self._last_timeout,
            "last_cleanup": self._last_cleanup,
        }

    def _safe_health_call(self, fn) -> dict:
        try:
            value = fn()
            return value if isinstance(value, dict) else {"available": True, "value": _jsonable(value)}
        except Exception as exc:
            return {
                "available": False,
                "error": f"{type(exc).__name__}: {exc}",
            }

    def _resolve_exec_timeout(self, code: str, timeout_s: float | None) -> tuple[float | None, str]:
        direct_timeout = _coerce_timeout_s(timeout_s, source="run(timeout_s)")
        if direct_timeout is not None:
            return direct_timeout, "run(timeout_s)"

        option_timeout = _coerce_timeout_s(
            self._launch_options.get("exec_timeout_s"),
            source="driver_option:exec_timeout_s",
        )
        if option_timeout is not None:
            return option_timeout, "driver_option:exec_timeout_s"

        env_value = os.environ.get("SIM_HFSS_EXEC_TIMEOUT_S")
        env_timeout = _coerce_timeout_s(env_value, source="SIM_HFSS_EXEC_TIMEOUT_S")
        if env_timeout is not None:
            return env_timeout, "env:SIM_HFSS_EXEC_TIMEOUT_S"

        if _looks_like_solve_snippet(code):
            return None, "disabled:solve-snippet"
        return _DEFAULT_EXEC_TIMEOUT_S, "default"

    def _should_own_aedt_process(self, *, new_desktop: bool, machine: str, port: int) -> bool:
        return bool(new_desktop) and not machine and not port

    def _identify_owned_aedt_pids(
        self,
        *,
        owns_process: bool,
        before_pids: set[int],
        after_pids: set[int],
        runtime_pid: int | None,
    ) -> set[int]:
        if not owns_process:
            return set()
        if runtime_pid is not None and runtime_pid not in before_pids:
            return {runtime_pid}
        new_pids = after_pids - before_pids
        if len(new_pids) == 1:
            return set(new_pids)
        return set()

    def _release_desktop(self) -> list[str]:
        if self._hfss is None and self._desktop is None:
            return []
        errors: list[str] = []
        try:
            release = getattr(self._hfss, "release_desktop", None) if self._hfss is not None else None
            if callable(release):
                release(close_projects=False, close_desktop=True)
            elif self._desktop is not None:
                desktop_release = getattr(self._desktop, "release_desktop", None)
                if callable(desktop_release):
                    desktop_release(close_projects=False, close_desktop=True)
        except Exception as e:
            errors.append(f"{type(e).__name__}: {e}")
        return errors

    def _kill_owned_aedt_processes(self) -> dict:
        reports = []
        for pid in sorted(self._owned_aedt_pids):
            alive_before = _pid_is_alive(pid)
            kill_called = False
            kill_ok = False
            if alive_before:
                kill_called = True
                kill_ok = _kill_pid(pid)
                time.sleep(0.2)
            alive_after = _pid_is_alive(pid)
            reports.append({
                "pid": pid,
                "alive_before": alive_before,
                "kill_called": kill_called,
                "kill_ok": kill_ok,
                "alive_after": alive_after,
            })
        return {
            "owned_aedt_pids": sorted(self._owned_aedt_pids),
            "processes": reports,
        }

    def _cleanup_session(self, *, reason: str) -> dict:
        release_errors = self._release_desktop()
        kill_report = self._kill_owned_aedt_processes()
        cleanup = {
            "reason": reason,
            "release_errors": release_errors,
            **kill_report,
        }
        self._hfss = None
        self._desktop = None
        self._session_id = None
        self._owned_aedt_pids = set()
        self._last_cleanup = cleanup
        return cleanup

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

    def _model_summary(self) -> dict:
        hfss = self._hfss
        assert hfss is not None
        modeler = _safe_attr(hfss, "modeler")
        if modeler is None:
            return {"available": False, "message": "HFSS modeler is not available."}

        object_names = [str(name) for name in _as_list(_safe_attr(modeler, "object_names", []))]
        solid_names = {str(name) for name in _as_list(_safe_attr(modeler, "solid_names", []))}
        sheet_names = {str(name) for name in _as_list(_safe_attr(modeler, "sheet_names", []))}
        objects_by_name: dict[str, object] = {}
        raw_objects = _safe_attr(modeler, "objects", {})
        if isinstance(raw_objects, dict):
            for value in raw_objects.values():
                objects_by_name[_name_of(value)] = value

        summaries = []
        for name in object_names:
            obj = objects_by_name.get(name)
            kind = "sheet" if name in sheet_names else "solid" if name in solid_names else "unknown"
            summaries.append({
                "name": name,
                "kind": kind,
                "material": _jsonable(_safe_attr(obj, "material_name") if obj is not None else None),
                "bounding_box": _jsonable(_safe_attr(obj, "bounding_box") if obj is not None else None),
            })

        return {
            "available": True,
            "object_count": len(object_names),
            "solid_count": len(solid_names),
            "sheet_count": len(sheet_names),
            "objects": summaries,
        }

    def _boundaries_summary(self) -> dict:
        hfss = self._hfss
        assert hfss is not None
        boundaries = []
        for boundary in _as_list(_safe_attr(hfss, "boundaries", [])):
            props = _safe_attr(boundary, "props", {})
            objects = []
            if isinstance(props, dict):
                for key in ("Objects", "Faces", "Edges", "Terminals"):
                    objects.extend(str(item) for item in _as_list(props.get(key)))
            boundaries.append({
                "name": _name_of(boundary),
                "type": _jsonable(_safe_attr(boundary, "type") or _safe_attr(boundary, "boundary_type")),
                "objects": sorted(set(objects)),
            })

        return {
            "available": True,
            "boundary_count": len(boundaries),
            "boundaries": boundaries,
            "excitation_names": _jsonable(_safe_attr(hfss, "excitation_names", [])),
        }

    def _setups_summary(self) -> dict:
        hfss = self._hfss
        assert hfss is not None
        setup_names = [str(name) for name in _as_list(_safe_attr(hfss, "setup_names", []))]
        raw_setups = _as_list(_safe_attr(hfss, "setups", []))
        setups_by_name = {_name_of(setup): setup for setup in raw_setups}

        setups = []
        for name in setup_names:
            setup = setups_by_name.get(name)
            sweeps = []
            for sweep in _as_list(_safe_attr(setup, "sweeps", []) if setup is not None else []):
                sweeps.append({
                    "name": _name_of(sweep),
                    "type": _jsonable(_safe_attr(sweep, "type") or _safe_attr(sweep, "sweep_type")),
                    "props": _jsonable(_safe_attr(sweep, "props", {})),
                })
            setups.append({
                "name": name,
                "props": _jsonable(_safe_attr(setup, "props", {}) if setup is not None else {}),
                "sweeps": sweeps,
            })

        return {
            "available": True,
            "setup_count": len(setup_names),
            "setups": setups,
        }

    def _messages_summary(self) -> dict:
        hfss = self._hfss
        assert hfss is not None
        desktop = _safe_attr(hfss, "odesktop") or self._desktop
        if desktop is None:
            return {"available": False, "messages": [], "message": "AEDT desktop object is not available."}

        raw_messages = _safe_call(desktop, "GetMessages", "", "", 0, default=None)
        if raw_messages is None:
            raw_messages = _safe_call(desktop, "GetMessages", "", "", 2, default=[])
        messages = [_parse_message(message) for message in _as_list(raw_messages)]
        return {
            "available": True,
            "count": len(messages),
            "messages": messages,
        }

    def _solution_progress(self) -> dict:
        hfss = self._hfss
        assert hfss is not None
        project_file = _safe_attr(hfss, "project_file")
        if not project_file:
            return {"available": False, "message": "project_file is not available."}

        project_path = Path(str(project_file))
        results_dir = Path(str(project_path) + "results")
        if not results_dir.exists():
            return {
                "available": False,
                "project_file": str(project_path),
                "results_dir": str(results_dir),
                "message": "AEDT results directory was not found.",
            }

        solved = []
        for path in results_dir.rglob("*_SU.txt"):
            record = _read_su_file(path)
            if record is not None:
                solved.append(record)
        solved.sort(key=lambda row: (row.get("frequency_ghz") is None, row.get("frequency_ghz", 0)))
        latest = max(solved, key=lambda row: Path(str(row["path"])).stat().st_mtime) if solved else None

        return {
            "available": True,
            "project_file": str(project_path),
            "results_dir": str(results_dir),
            "completed_frequency_count": len(solved),
            "latest": latest,
            "frequencies_ghz": [row.get("frequency_ghz") for row in solved if row.get("frequency_ghz") is not None],
            "success_count": sum(1 for row in solved if row.get("success") is True),
        }
