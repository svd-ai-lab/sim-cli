"""Fixed query handlers for the PyFluent driver."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sim.drivers.fluent.runtime import PyFluentRuntime

# Ordered list of workflow attribute names to probe
_WORKFLOW_ATTRS = ("workflow", "meshing_workflow", "watertight")


def handle_query(name: str, runtime: "PyFluentRuntime") -> dict:
    """Dispatch a named query and return a structured dict."""
    handlers = {
        "session.summary": _session_summary,
        "workflow.summary": _workflow_summary,
        "last.result": _last_result,
        "field.catalog": _field_catalog,
    }
    fn = handlers.get(name)
    if fn is None:
        raise ValueError(
            f"Unknown query '{name}'. Available: {sorted(handlers)}"
        )
    return fn(runtime)


def _session_summary(runtime: "PyFluentRuntime") -> dict:
    info = runtime.get_active_session()
    if info is None:
        return {"session_id": None, "solver_kind": None, "has_last_run": False}
    return {
        "session_id": info.session_id,
        "solver_kind": info.mode,
        "has_last_run": runtime.last_record is not None,
    }


def _workflow_summary(runtime: "PyFluentRuntime") -> dict:
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
        if hasattr(session, attr):
            obj = getattr(session, attr)
            return {
                "session_id": info.session_id,
                "solver_kind": info.mode,
                "workflow_attr": attr,
                "workflow_repr": repr(obj)[:200],
            }

    return {
        "session_id": info.session_id,
        "solver_kind": info.mode,
        "workflow_available": False,
        "reason": "no meshing workflow attribute detected",
    }


def _last_result(runtime: "PyFluentRuntime") -> dict:
    rec = runtime.last_record
    if rec is None:
        return {"has_last_run": False}
    return {
        "has_last_run": True,
        "run_id": rec.run_id,
        "label": rec.label,
        "ok": rec.ok,
        "stdout": rec.stdout,
        "stderr": rec.stderr,
        "error": rec.error,
        "result": rec.result,
    }


def _field_catalog(runtime: "PyFluentRuntime") -> dict:
    info = runtime.get_active_session()
    if info is None:
        return {"available": False, "reason": "no active session"}

    session = info.session
    if not hasattr(session, "fields"):
        return {"available": False, "reason": "session has no fields interface"}

    try:
        fd = session.fields.field_data
        scalar_names = list(getattr(fd, "get_scalar_field_names", lambda: [])())
        vector_names = list(getattr(fd, "get_vector_field_names", lambda: [])())
        surfaces_info = getattr(session.fields, "get_surfaces_info", lambda: {})()
        surface_names = list(surfaces_info.keys())
        return {
            "available": True,
            "scalar_names": scalar_names,
            "vector_names": vector_names,
            "surface_names": surface_names,
        }
    except Exception as exc:
        return {
            "available": False,
            "reason": f"fields interface present but could not enumerate: {exc}",
        }
