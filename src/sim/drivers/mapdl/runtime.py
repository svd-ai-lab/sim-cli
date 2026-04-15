"""MAPDL persistent session runtime (Phase 2).

Unlike LS-DYNA, MAPDL exposes a **live gRPC server** we can talk to
across `sim exec` calls — the `Mapdl` client object is the session.
Unlike Mechanical, user snippets run in **sim's Python namespace**
(not inside the solver's interpreter), so every `mapdl.foo(...)` call
is a gRPC round-trip from sim to the ANSYS<ver>.exe subprocess.

Namespace exposed to snippets:
  - `mapdl`          : live `Mapdl` gRPC client
  - `np`             : numpy shortcut (nearly every post-op needs it)
  - `launch_mapdl`   : in case the snippet wants to detach / re-launch
  - `workdir`        : `Path` of MAPDL working directory
  - `_result`        : assignable, returned to caller

Query targets (via `sim inspect`):
  - `session.summary`  — solver alive, version, cwd, jobname
  - `mesh.summary`     — node/element counts and element types
  - `workdir.files`    — files on disk (.rst, .db, .log, .png)
  - `results.summary`  — load steps / substeps if .rst exists
  - `last.result`      — previous exec record (handled by server fallback)
"""
from __future__ import annotations

import contextlib
import io
import tempfile
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class _SessionState:
    workdir: Path
    namespace: dict = field(default_factory=dict)
    runs: list[dict] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    mapdl_obj: Any = None          # the live Mapdl client
    session_id: str = ""


class MapdlSessionRuntime:
    """Owns one live MAPDL gRPC session + snippet exec dispatcher."""

    def __init__(self) -> None:
        self._state: _SessionState | None = None

    # ------------------------------------------------------------------ launch

    def launch(
        self,
        workdir: str | Path | None = None,
        exec_file: str | None = None,
        nproc: int | None = None,
        **_kwargs: Any,
    ) -> dict:
        """Start a live MAPDL gRPC server and connect.

        Ignored-but-accepted kwargs (protocol compatibility with other
        drivers): ``mode``, ``ui_mode``, ``processors``. MAPDL-specific
        kwargs override: ``nproc`` (preferred name for MPI ranks).
        """
        import warnings
        warnings.filterwarnings("ignore", category=DeprecationWarning)

        # Import lazily so the driver itself stays importable when
        # pymapdl isn't installed (one-shot / detect-only paths).
        try:
            from ansys.mapdl.core import Mapdl, launch_mapdl  # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                "pymapdl (ansys-mapdl-core) not installed — "
                "`uv pip install ansys-mapdl-core` to enable session mode."
            ) from e

        # Resolve workdir
        if workdir is None:
            wd = Path(tempfile.mkdtemp(prefix="sim_mapdl_"))
        else:
            wd = Path(workdir)
            wd.mkdir(parents=True, exist_ok=True)

        # Prefer "nproc" but also honour "processors" from the generic
        # /connect protocol — whichever is set wins, nproc takes precedence.
        kwargs: dict[str, Any] = {"run_location": str(wd), "loglevel": "ERROR"}
        if exec_file:
            kwargs["exec_file"] = exec_file
        if nproc:
            kwargs["nproc"] = int(nproc)
        elif "processors" in _kwargs and _kwargs["processors"]:
            kwargs["nproc"] = int(_kwargs["processors"])

        mapdl = launch_mapdl(**kwargs)

        # Import numpy eagerly so user snippets don't need the import line.
        import numpy as np

        ns: dict[str, Any] = {
            "mapdl": mapdl,
            "np": np,
            "launch_mapdl": launch_mapdl,
            "workdir": wd,
            "_result": None,
        }

        session_id = f"mapdl-{int(time.time())}"
        self._state = _SessionState(
            workdir=wd,
            namespace=ns,
            mapdl_obj=mapdl,
            session_id=session_id,
        )

        return {
            "ok": True,
            "session_id": session_id,
            "workdir": str(wd),
            "mapdl_version": str(getattr(mapdl, "version", "?")),
            "pymapdl_available": True,
            "nproc": kwargs.get("nproc"),
        }

    # ------------------------------------------------------------------ exec

    def exec_snippet(self, code: str, label: str = "snippet") -> dict:
        if self._state is None:
            return {"ok": False, "error": "No active session — call launch() first"}

        ns = self._state.namespace
        ns["_result"] = None

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        start = time.monotonic()
        error: str | None = None
        ok = True

        try:
            with (
                contextlib.redirect_stdout(stdout_buf),
                contextlib.redirect_stderr(stderr_buf),
            ):
                exec(code, ns)
        except Exception as e:
            ok = False
            error = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"

        elapsed = time.monotonic() - start

        result_value = ns.get("_result")

        run_record = {
            "ok": ok,
            "label": label,
            "stdout": stdout_buf.getvalue(),
            "stderr": stderr_buf.getvalue(),
            "error": error,
            "result": _coerce_result(result_value),
            "elapsed_s": round(elapsed, 4),
        }
        self._state.runs.append(run_record)
        return run_record

    # ------------------------------------------------------------------ query

    def query(self, name: str) -> dict:
        if self._state is None:
            return {"ok": False, "error": "No active session"}

        ns = self._state.namespace
        mapdl = ns.get("mapdl")

        if name in ("session.summary", "session"):
            return {
                "ok": True,
                "session_id": self._state.session_id,
                "workdir": str(self._state.workdir),
                "mapdl_version": str(getattr(mapdl, "version", "?")) if mapdl else None,
                "jobname": _safe(lambda: mapdl.jobname),
                "directory": _safe(lambda: str(mapdl.directory)),
                "n_runs": len(self._state.runs),
                "alive": mapdl is not None,
            }

        if name in ("mesh.summary", "mesh"):
            if mapdl is None:
                return {"ok": False, "error": "No mapdl client"}
            try:
                nnum = mapdl.mesh.nnum
                enum = mapdl.mesh.enum
                etypes = _safe(lambda: sorted(set(int(e[0]) for e in mapdl.mesh.elem))) or []
                return {
                    "ok": True,
                    "n_nodes": int(len(nnum)),
                    "n_elements": int(len(enum)),
                    "element_type_ids": etypes,
                }
            except Exception as e:
                return {"ok": False, "error": f"mesh query failed: {e}"}

        if name in ("workdir.files", "files"):
            files = sorted(p.name for p in self._state.workdir.iterdir() if p.is_file())
            return {
                "ok": True,
                "workdir": str(self._state.workdir),
                "files": files,
                "n_files": len(files),
                "has_rst": any(f.endswith(".rst") for f in files),
                "has_db": any(f.endswith(".db") for f in files),
                "pngs": [f for f in files if f.endswith(".png")],
            }

        if name in ("results.summary", "results"):
            if mapdl is None:
                return {"ok": False, "error": "No mapdl client"}
            try:
                result = mapdl.result     # ansys.mapdl.reader.Result
                n_ls = int(result.nsets)
                return {
                    "ok": True,
                    "n_result_sets": n_ls,
                    "time_values": [float(t) for t in getattr(result, "time_values", [])][:20],
                    "available_methods": [
                        m for m in (
                            "nodal_solution",
                            "principal_nodal_stress",
                            "plot_nodal_solution",
                            "plot_principal_nodal_stress",
                        ) if hasattr(result, m)
                    ],
                }
            except Exception as e:
                return {"ok": False, "error": f"result query failed (need .rst on disk): {e}"}

        if name in ("last.result", "last"):
            if not self._state.runs:
                return {"ok": False, "error": "No runs yet"}
            return {"ok": True, **self._state.runs[-1]}

        return {"ok": False, "error": f"Unknown query: {name}"}

    # ------------------------------------------------------------------ disconnect

    def disconnect(self) -> dict:
        if self._state is None:
            return {"ok": True, "disconnected": True, "note": "no active session"}

        mapdl = self._state.mapdl_obj
        err: str | None = None
        if mapdl is not None:
            try:
                mapdl.exit()
            except Exception as e:
                err = f"{type(e).__name__}: {e}"

        wd = str(self._state.workdir)
        n_runs = len(self._state.runs)
        self._state = None
        return {
            "ok": True,
            "disconnected": True,
            "workdir": wd,
            "n_runs": n_runs,
            "exit_error": err,
        }


# --- helpers ---------------------------------------------------------------


def _safe(fn):
    try:
        return fn()
    except Exception:
        return None


def _coerce_result(value):
    """Best-effort JSON-safe conversion."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool, list, dict)):
        return value
    try:
        import numpy as np
        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, np.generic):
            return value.item()
    except ImportError:
        pass
    return repr(value)
