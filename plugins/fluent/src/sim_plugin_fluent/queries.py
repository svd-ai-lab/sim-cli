"""Best-effort query handlers for live PyFluent sessions."""
from __future__ import annotations

import importlib.metadata as metadata
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .artifacts import list_fluent_files

if TYPE_CHECKING:
    from .runtime import PyFluentRuntime


_WORKFLOW_ATTRS = ("workflow", "meshing_workflow", "watertight")
_BOUNDARY_FAMILIES = (
    "velocity_inlet",
    "pressure_inlet",
    "mass_flow_inlet",
    "pressure_outlet",
    "outflow",
    "wall",
    "symmetry",
    "interface",
)
_MODEL_NAMES = (
    "energy",
    "viscous",
    "species",
    "radiation",
    "multiphase",
    "discrete_phase",
    "acoustics",
)
_ALIASES = {
    "fluent.field.catalog": "field.catalog",
    "fluent.session.health": "session.health",
    "fluent.session.versions": "session.versions",
}


def handle_query(name: str, runtime: "PyFluentRuntime", *, driver: object | None = None) -> dict:
    """Dispatch a named query and return a structured dict."""
    canonical = _ALIASES.get(name, name)
    handlers = {
        "session.summary": _session_summary,
        "session.health": _session_health,
        "session.versions": _session_versions,
        "workflow.summary": _workflow_summary,
        "last.result": _last_result,
        "field.catalog": _field_catalog,
        "fluent.models.summary": _models_summary,
        "fluent.boundaries.summary": _boundaries_summary,
        "fluent.case.summary": _case_summary,
        "fluent.mesh.summary": _mesh_summary,
        "fluent.files": _fluent_files,
        "fluent.transcript.tail": _transcript_tail,
    }
    fn = handlers.get(canonical)
    if fn is None:
        available = sorted(set(handlers) | set(_ALIASES))
        raise ValueError(f"Unknown query '{name}'. Available: {available}")
    result = fn(runtime, driver=driver)
    result.setdefault("query", canonical)
    if canonical != name:
        result.setdefault("alias", name)
    return result


def _session_summary(runtime: "PyFluentRuntime", *, driver: object | None = None) -> dict:
    info = runtime.get_active_session()
    if info is None:
        return {
            "connected": False,
            "session_id": None,
            "solver_kind": None,
            "has_last_run": runtime.last_record is not None,
            "run_count": runtime.run_count,
        }
    return {
        "connected": True,
        "session_id": info.session_id,
        "solver_kind": info.mode,
        "source": info.source,
        "launch_options": info.launch_options or {},
        "workdir": _workdir(runtime),
        "has_last_run": runtime.last_record is not None,
        "last_ok": None if runtime.last_record is None else runtime.last_record.ok,
        "run_count": runtime.run_count,
    }


def _session_health(runtime: "PyFluentRuntime", *, driver: object | None = None) -> dict:
    info = runtime.get_active_session()
    if info is None:
        return {
            "ok": False,
            "connected": False,
            "reason": "no active session",
            "run_count": runtime.run_count,
        }

    session = info.session
    interfaces = {
        name: _safe_get(session, name) is not None
        for name in ("settings", "setup", "tui", "fields", "workflow")
    }
    checks: dict[str, Any] = {}
    for method_name in ("is_active", "is_server_healthy", "health_check"):
        method = _safe_get(session, method_name)
        if callable(method):
            value, error = _call_safely(method)
            checks[method_name] = value if error is None else {"error": error}
            break

    last_error = None
    if runtime.last_record is not None and not runtime.last_record.ok:
        last_error = _sanitize_message(runtime.last_record.error or "")

    return {
        "ok": last_error is None,
        "connected": True,
        "session_id": info.session_id,
        "solver_kind": info.mode,
        "source": info.source,
        "workdir": _workdir(runtime),
        "run_count": runtime.run_count,
        "last_ok": None if runtime.last_record is None else runtime.last_record.ok,
        "last_error": last_error,
        "interfaces": interfaces,
        "checks": checks,
    }


def _session_versions(runtime: "PyFluentRuntime", *, driver: object | None = None) -> dict:
    pyfluent_version = _package_version("ansys-fluent-core")
    plugin_version = _package_version("sim-plugin-fluent")
    installs = _installed_summary(driver)
    info = runtime.get_active_session()
    active_solver_version = active_fluent_version(
        None if info is None else info.session
    )
    profile = _resolve_profile(
        installs,
        pyfluent_version,
        active_solver_version=active_solver_version,
    )

    return {
        "driver": {
            "package": "sim-plugin-fluent",
            "version": plugin_version,
        },
        "sdk": {
            "package": "ansys-fluent-core",
            "version": pyfluent_version,
        },
        "fluent": {
            "detected": installs,
            "active_session": None
            if info is None
            else {
                "session_id": info.session_id,
                "solver_kind": info.mode,
                "source": info.source,
                "solver_version": active_solver_version,
            },
        },
        "compatibility": profile,
    }


def _workflow_summary(runtime: "PyFluentRuntime", *, driver: object | None = None) -> dict:
    info = runtime.get_active_session()
    if info is None:
        return {
            "session_id": None,
            "solver_kind": None,
            "workflow_available": False,
            "reason": "no active session",
        }

    session = info.session
    for attr in _WORKFLOW_ATTRS:
        obj = _safe_get(session, attr)
        if obj is not None:
            return {
                "session_id": info.session_id,
                "solver_kind": info.mode,
                "workflow_available": True,
                "workflow_attr": attr,
                "workflow_repr": _short_repr(obj),
                "children": _child_names(obj),
            }

    return {
        "session_id": info.session_id,
        "solver_kind": info.mode,
        "workflow_available": False,
        "reason": "no meshing workflow attribute detected",
    }


def _last_result(runtime: "PyFluentRuntime", *, driver: object | None = None) -> dict:
    rec = runtime.last_record
    if rec is None:
        return {"has_last_run": False, "run_count": runtime.run_count}
    return {
        "has_last_run": True,
        "run_count": runtime.run_count,
        "run_id": rec.run_id,
        "label": rec.label,
        "ok": rec.ok,
        "stdout": rec.stdout,
        "stderr": rec.stderr,
        "error": rec.error,
        "result": rec.result,
    }


def _field_catalog(runtime: "PyFluentRuntime", *, driver: object | None = None) -> dict:
    info = runtime.get_active_session()
    if info is None:
        return {"available": False, "reason": "no active session"}

    session = info.session
    fields = _safe_get(session, "fields")
    if fields is None:
        return {"available": False, "reason": "session has no fields interface"}

    try:
        fd = _safe_get(fields, "field_data") or fields
        scalar_names = list(_call_optional(_safe_get(fd, "get_scalar_field_names"), default=[]))
        vector_names = list(_call_optional(_safe_get(fd, "get_vector_field_names"), default=[]))
        surfaces_info_fn = _safe_get(fields, "get_surfaces_info") or _safe_get(fd, "get_surfaces_info")
        surfaces_info = _call_optional(surfaces_info_fn, default={})
        surface_names = list(surfaces_info.keys()) if isinstance(surfaces_info, dict) else []
        return {
            "available": True,
            "scalar_names": scalar_names,
            "vector_names": vector_names,
            "surface_names": surface_names,
        }
    except Exception as exc:  # noqa: BLE001 - query must degrade gracefully
        return {
            "available": False,
            "reason": f"fields interface present but could not enumerate: {_sanitize_exception(exc)}",
        }


def _models_summary(runtime: "PyFluentRuntime", *, driver: object | None = None) -> dict:
    info = runtime.get_active_session()
    if info is None:
        return {"available": False, "reason": "no active session"}
    models = _safe_get(_safe_get(info.session, "setup"), "models")
    if models is None:
        return {"available": False, "reason": "session has no setup.models interface"}

    rows: dict[str, dict] = {}
    for name in _MODEL_NAMES:
        obj = _safe_get(models, name)
        if obj is not None:
            rows[name] = _object_summary(obj)
    children = _child_names(models)
    return {
        "available": True,
        "session_id": info.session_id,
        "solver_kind": info.mode,
        "models": rows,
        "children": children,
    }


def _boundaries_summary(runtime: "PyFluentRuntime", *, driver: object | None = None) -> dict:
    info = runtime.get_active_session()
    if info is None:
        return {"available": False, "reason": "no active session"}
    bc = _safe_get(_safe_get(info.session, "setup"), "boundary_conditions")
    if bc is None:
        return {"available": False, "reason": "session has no boundary_conditions interface"}

    families: dict[str, list[str]] = {}
    for family in _BOUNDARY_FAMILIES:
        obj = _safe_get(bc, family)
        if obj is not None:
            families[family] = _child_names(obj)

    state = _state_snapshot(bc)
    if isinstance(state, dict):
        for family, value in state.items():
            if family not in families and isinstance(value, dict):
                families[family] = list(value.keys())

    return {
        "available": True,
        "session_id": info.session_id,
        "solver_kind": info.mode,
        "families": families,
    }


def _case_summary(runtime: "PyFluentRuntime", *, driver: object | None = None) -> dict:
    info = runtime.get_active_session()
    if info is None:
        return {"available": False, "reason": "no active session"}
    session = info.session
    file_iface = (
        _safe_get(_safe_get(session, "settings"), "file")
        or _safe_get(session, "file")
        or _safe_get(_safe_get(session, "setup"), "file")
    )
    return {
        "available": True,
        "session_id": info.session_id,
        "solver_kind": info.mode,
        "workdir": _workdir(runtime),
        "file_interface_available": file_iface is not None,
        "file_methods": _available_methods(
            file_iface,
            (
                "read_case",
                "read_case_data",
                "write_case",
                "write_case_data",
                "read_data",
                "write_data",
            ),
        ),
    }


def _mesh_summary(runtime: "PyFluentRuntime", *, driver: object | None = None) -> dict:
    info = runtime.get_active_session()
    if info is None:
        return {"available": False, "reason": "no active session"}
    session = info.session
    mesh_obj = (
        _safe_get(_safe_get(session, "setup"), "mesh")
        or _safe_get(session, "mesh")
        or _safe_get(session, "meshing")
    )
    if mesh_obj is None:
        return {
            "available": False,
            "session_id": info.session_id,
            "solver_kind": info.mode,
            "reason": "no mesh interface detected",
        }
    return {
        "available": True,
        "session_id": info.session_id,
        "solver_kind": info.mode,
        "mesh_repr": _short_repr(mesh_obj),
        "children": _child_names(mesh_obj),
        "state": _state_snapshot(mesh_obj),
    }


def _fluent_files(runtime: "PyFluentRuntime", *, driver: object | None = None) -> dict:
    root = Path(_workdir(runtime))
    files = list_fluent_files(root)
    return {
        "available": root.is_dir(),
        "root": str(root),
        "count": len(files),
        "files": files,
    }


def _transcript_tail(runtime: "PyFluentRuntime", *, driver: object | None = None) -> dict:
    root = Path(_workdir(runtime))
    candidates = [
        item
        for item in list_fluent_files(root, max_files=50)
        if item["role"] in {"fluent-transcript", "fluent-log", "fluent-journal"}
    ]
    tails: list[dict] = []
    for item in candidates[:5]:
        path = Path(item["path"])
        try:
            text = path.read_text(encoding="utf-8", errors="replace")[-4000:]
        except OSError as exc:
            tails.append({**item, "tail_available": False, "reason": _sanitize_exception(exc)})
            continue
        tails.append({**item, "tail_available": True, "tail": _sanitize_tail(text)})
    return {
        "available": bool(tails),
        "root": str(root),
        "files": tails,
    }


def _workdir(runtime: "PyFluentRuntime") -> str:
    info = runtime.get_active_session()
    if info is not None:
        raw = (info.launch_options or {}).get("cwd")
        if raw:
            return str(Path(raw))
    return str(runtime.sim_dir)


def _installed_summary(driver: object | None) -> list[dict]:
    if driver is None or not hasattr(driver, "detect_installed"):
        return []
    try:
        installs = list(driver.detect_installed())
    except Exception:  # noqa: BLE001 - version query should not fail
        return []
    rows: list[dict] = []
    for install in installs:
        extra = getattr(install, "extra", {}) or {}
        rows.append(
            {
                "version": getattr(install, "version", None),
                "source": _source_class(getattr(install, "source", "")),
                "release_code": extra.get("release_code"),
                "release_label": extra.get("release_label"),
            }
        )
    return rows


def _resolve_profile(
    installs: list[dict],
    pyfluent_version: str | None,
    *,
    active_solver_version: str | None = None,
) -> dict | None:
    try:
        from sim.compat import load_compatibility_by_name  # noqa: PLC0415

        compat = load_compatibility_by_name("fluent")
    except Exception:  # noqa: BLE001
        compat = None
    if compat is None:
        return None

    if active_solver_version:
        profile = compat.resolve(active_solver_version)
        return None if profile is None else profile.to_dict()

    profile = None
    for install in installs:
        version = install.get("version")
        if version:
            profile = compat.resolve(version)
            if profile is not None:
                break
    if profile is None and pyfluent_version:
        if pyfluent_version.startswith("0.38"):
            profile = compat.profile_by_name("pyfluent_0_38_modern")
        elif pyfluent_version.startswith("0.37"):
            profile = compat.profile_by_name("pyfluent_0_37_legacy")
    return None if profile is None else profile.to_dict()


def normalize_runtime_fluent_version(value: object) -> str | None:
    """Normalize a live ``get_fluent_version()`` value to ``YY.R``."""
    if value is None:
        return None
    candidates = (
        getattr(value, "value", None),
        getattr(value, "name", None),
        str(value),
    )
    for candidate in candidates:
        if candidate is None:
            continue
        text = str(candidate).strip()
        match = re.search(r"(?<!\d)(20)?(\d{2})[._](\d)(?:\.\d+)?", text)
        if match:
            return f"{match.group(2)}.{match.group(3)}"
        match = re.search(r"\bv?(\d{3})\b", text, re.IGNORECASE)
        if match:
            code = match.group(1)
            return f"{code[:2]}.{code[2]}"
    return None


def active_fluent_version(session: object | None) -> str | None:
    method = _safe_get(session, "get_fluent_version")
    if not callable(method):
        return None
    value, error = _call_safely(method)
    if error is not None:
        return None
    return normalize_runtime_fluent_version(value)


def _package_version(package: str) -> str | None:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return None


def _source_class(source: str) -> str:
    if not source:
        return ""
    return source.split(":", 1)[0]


def _safe_get(obj: object | None, attr: str) -> Any:
    if obj is None:
        return None
    try:
        return getattr(obj, attr)
    except Exception:  # noqa: BLE001 - PyFluent settings may raise during lookup
        return None


def _call_safely(fn: object) -> tuple[Any, str | None]:
    try:
        return fn(), None  # type: ignore[misc]
    except Exception as exc:  # noqa: BLE001
        return None, _sanitize_exception(exc)


def _call_optional(fn: object, *, default: object) -> object:
    if not callable(fn):
        return default
    value, error = _call_safely(fn)
    return default if error is not None else value


def _available_methods(obj: object | None, names: tuple[str, ...]) -> list[str]:
    if obj is None:
        return []
    return [name for name in names if callable(_safe_get(obj, name))]


def _child_names(obj: object | None) -> list[str]:
    if obj is None:
        return []
    if isinstance(obj, dict):
        return [str(key) for key in obj.keys()]
    for attr in ("child_names", "get_object_names", "allowed_values"):
        value = _safe_get(obj, attr)
        if callable(value):
            value = _call_optional(value, default=[])
        if isinstance(value, (list, tuple, set)):
            return [str(item) for item in value]
        if isinstance(value, dict):
            return [str(key) for key in value.keys()]
    return []


def _object_summary(obj: object) -> dict:
    state = _state_snapshot(obj)
    summary: dict[str, Any] = {}
    if isinstance(state, (str, int, float, bool)) or state is None:
        summary["state"] = state
    elif isinstance(state, (dict, list, tuple)):
        summary["state"] = state

    for attr in ("enabled", "model", "option", "type"):
        value = _safe_get(obj, attr)
        if value is None:
            continue
        state_value = _state_snapshot(value)
        if _jsonish(state_value):
            summary[attr] = state_value

    if not summary:
        summary["repr"] = _short_repr(obj)
    return summary


def _state_snapshot(obj: object | None) -> object:
    if obj is None:
        return None
    if _jsonish(obj):
        return obj
    for attr in ("get_state", "get_object_value", "get_value"):
        method = _safe_get(obj, attr)
        if callable(method):
            value, error = _call_safely(method)
            if error is None and _jsonish(value):
                return value
    if callable(obj):
        value, error = _call_safely(obj)
        if error is None and _jsonish(value):
            return value
    return None


def _jsonish(value: object) -> bool:
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, (list, tuple)):
        return all(_jsonish(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _jsonish(item) for key, item in value.items())
    return False


def _short_repr(obj: object, *, limit: int = 200) -> str:
    try:
        text = repr(obj)
    except Exception:  # noqa: BLE001
        text = f"<{type(obj).__name__}>"
    return text[:limit]


def _sanitize_exception(exc: BaseException) -> str:
    return _sanitize_message(f"{type(exc).__name__}: {exc}")


def _sanitize_message(message: str) -> str:
    text = str(message).strip()
    low = text.lower()
    sensitive = ("license", "licence", "entitlement", "ansyslmd", "lmgrd")
    if any(token in low for token in sensitive):
        return "Fluent startup/runtime error; inspect local logs for details"
    return text[:500]


def _sanitize_tail(text: str) -> str:
    lines = []
    for line in text.splitlines()[-80:]:
        lines.append(_sanitize_message(line))
    return "\n".join(lines)
