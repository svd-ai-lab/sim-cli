"""LS-DYNA persistent session runtime.

Unlike Fluent / CFX / Mechanical, LS-DYNA itself has no interactive
process you can talk to. The "session" here is a **Python namespace**
that persists across `sim exec` calls, holding:

  - `deck`     : the PyDyna `Deck` being built (PyDyna keywords API)
  - `kwd`      : shortcut to `ansys.dyna.core.keywords`
  - `Deck`     : the `Deck` class (for `deck = Deck()` rebuilds)
  - `workdir`  : working directory `Path` for solver IO
  - `run_dyna` : shortcut to `ansys.dyna.core.run.run_dyna`
  - `model`    : DPF `Model` (populated after the first solve)
  - `dpf`      : shortcut to `ansys.dpf.core` (for advanced post)
  - `_result`  : assignable for caller-friendly return values

Solver calls (`run_dyna(...)`) are still one-shot subprocesses — the
*session* is the Python state around those calls, not a live solver.
"""
from __future__ import annotations

import contextlib
import io
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class _SessionState:
    """Mutable state held by the runtime for one active session."""

    workdir: Path
    namespace: dict = field(default_factory=dict)
    runs: list[dict] = field(default_factory=list)
    last_solve: dict | None = None  # metadata of last run_dyna call
    awp_root: Path | None = None
    started_at: float = field(default_factory=time.time)


class LsDynaSessionRuntime:
    """Owns the per-session Python namespace and exec dispatcher."""

    def __init__(self) -> None:
        self._state: _SessionState | None = None

    # ------------------------------------------------------------------ launch

    def launch(
        self,
        workdir: str | Path | None = None,
        awp_root: str | Path | None = None,
        **_kwargs: Any,
    ) -> dict:
        """Initialize a new session.

        Imports PyDyna lazily so the driver remains importable even when
        `ansys-dyna-core` is not installed (one-shot mode still works).
        """
        try:
            from ansys.dyna.core import Deck, keywords as kwd  # noqa: F401
            from ansys.dyna.core.run import run_dyna  # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                "PyDyna SDK not installed — `pip install ansys-dyna-core` "
                f"to use session mode. ImportError: {e}"
            ) from e

        # Resolve working dir
        if workdir is None:
            import tempfile
            wd = Path(tempfile.mkdtemp(prefix="sim_lsdyna_"))
        else:
            wd = Path(workdir)
            wd.mkdir(parents=True, exist_ok=True)

        # Try to detect AWP_ROOT for downstream DPF use
        awp = Path(awp_root) if awp_root else None
        if awp is None:
            import os
            for env_key, env_val in os.environ.items():
                if env_key.startswith("AWP_ROOT"):
                    awp = Path(env_val)
                    break
            if awp is None:
                # Default scan
                for drive in ("C", "D", "E"):
                    base = Path(f"{drive}:/Program Files/ANSYS Inc")
                    if base.is_dir():
                        for child in sorted(base.iterdir(), reverse=True):
                            if child.name.startswith("v"):
                                awp = child
                                break
                        if awp:
                            break

        # Build the namespace exposed to user snippets
        from ansys.dyna.core import Deck as _Deck
        from ansys.dyna.core import keywords as _kwd
        from ansys.dyna.core.run import run_dyna as _run_dyna

        deck = _Deck()
        ns: dict = {
            # Core PyDyna handles
            "deck": deck,
            "kwd": _kwd,
            "Deck": _Deck,
            "run_dyna": _run_dyna,
            # Workspace
            "workdir": wd,
            # Post-processing handles (lazy)
            "model": None,
            "dpf": None,
            # Snippet interface
            "_result": None,
        }

        # Try to import DPF lazily — non-fatal if missing
        try:
            import ansys.dpf.core as _dpf
            ns["dpf"] = _dpf
        except ImportError:
            pass

        self._state = _SessionState(
            workdir=wd,
            namespace=ns,
            awp_root=awp,
        )

        return {
            "ok": True,
            "session_id": f"lsdyna-{int(self._state.started_at)}",
            "workdir": str(wd),
            "awp_root": str(awp) if awp else None,
            "pydyna_available": True,
            "dpf_available": ns["dpf"] is not None,
        }

    # ------------------------------------------------------------------ exec

    def exec_snippet(self, code: str, label: str = "snippet") -> dict:
        """Execute a Python snippet in the session namespace.

        The snippet has access to: `deck`, `kwd`, `Deck`, `workdir`,
        `run_dyna`, `model`, `dpf`. It can assign `_result = ...` to
        return data back to the caller.
        """
        if self._state is None:
            return {"ok": False, "error": "No active session — call launch() first"}

        # Reset _result for this run
        self._state.namespace["_result"] = None

        # If user just solved (run_dyna call), auto-load DPF model
        # (handled post-exec below)

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
                exec(code, self._state.namespace)
        except Exception as e:
            ok = False
            error = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"

        elapsed = time.monotonic() - start

        # If a d3plot now exists in workdir and model is None, auto-build it
        d3plot = self._state.workdir / "d3plot"
        if (
            ok
            and d3plot.is_file()
            and self._state.namespace.get("model") is None
            and self._state.namespace.get("dpf") is not None
        ):
            try:
                self._auto_load_model(d3plot)
            except Exception as e:
                stderr_buf.write(f"\n[warning] auto-DPF-model load failed: {e}\n")

        result_value = self._state.namespace.get("_result")

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

    def _auto_load_model(self, d3plot: Path) -> None:
        """Auto-instantiate DPF Model after first solve."""
        ns = self._state.namespace
        dpf = ns["dpf"]
        # Start local DPF server with the discovered AWP root
        try:
            if self._state.awp_root:
                dpf.start_local_server(ansys_path=str(self._state.awp_root))
        except Exception:
            # Server may already be running
            pass

        ds = dpf.DataSources()
        ds.set_result_file_path(str(d3plot), "d3plot")
        ns["model"] = dpf.Model(ds)
        ns["_data_sources"] = ds

    # ------------------------------------------------------------------ query

    def query(self, name: str) -> dict:
        """Named queries on session state."""
        if self._state is None:
            return {"ok": False, "error": "No active session"}

        ns = self._state.namespace
        deck = ns.get("deck")

        if name in ("session.summary", "session"):
            return {
                "ok": True,
                "session_id": f"lsdyna-{int(self._state.started_at)}",
                "workdir": str(self._state.workdir),
                "awp_root": str(self._state.awp_root) if self._state.awp_root else None,
                "deck_loaded": deck is not None,
                "n_runs": len(self._state.runs),
                "model_loaded": ns.get("model") is not None,
                "dpf_available": ns.get("dpf") is not None,
            }

        if name in ("deck.summary", "deck"):
            if deck is None:
                return {"ok": False, "error": "No deck in session"}
            try:
                n = len(deck)
            except Exception:
                n = None
            keyword_types = _summarize_keywords(deck)
            return {
                "ok": True,
                "title": getattr(deck, "title", None),
                "n_keywords": n,
                "keyword_types": keyword_types,
                "has_termination": "ControlTermination" in keyword_types,
                "has_nodes": any(k.startswith("Node") for k in keyword_types) or "Node" in keyword_types,
                "has_elements": any(k.startswith("Element") for k in keyword_types),
                "has_material": any(k.startswith("Mat") for k in keyword_types),
            }

        if name == "deck.text":
            if deck is None:
                return {"ok": False, "error": "No deck in session"}
            try:
                text = deck.write()
            except Exception as e:
                return {"ok": False, "error": f"deck.write() failed: {e}"}
            return {"ok": True, "text": text, "n_chars": len(text), "n_lines": text.count("\n") + 1}

        if name in ("workdir.files", "files"):
            files = sorted(p.name for p in self._state.workdir.iterdir() if p.is_file())
            d3plot_present = "d3plot" in files
            return {
                "ok": True,
                "workdir": str(self._state.workdir),
                "files": files,
                "n_files": len(files),
                "d3plot_present": d3plot_present,
            }

        if name in ("results.summary", "results"):
            model = ns.get("model")
            if model is None:
                return {"ok": False, "error": "No DPF model loaded — run a solve first or call dpf.Model() manually"}
            try:
                tfs = model.metadata.time_freq_support
                times = tfs.time_frequencies.data_as_list
                mesh = model.metadata.meshed_region
                return {
                    "ok": True,
                    "n_states": len(times),
                    "time_start": float(times[0]) if times else None,
                    "time_end": float(times[-1]) if times else None,
                    "n_nodes": int(mesh.nodes.n_nodes),
                    "n_elements": int(mesh.elements.n_elements),
                    "available_results": [str(r) for r in model.results.__dir__() if not r.startswith("_")][:30],
                }
            except Exception as e:
                return {"ok": False, "error": f"DPF model query failed: {e}"}

        if name in ("last.result", "last"):
            if not self._state.runs:
                return {"ok": False, "error": "No runs yet"}
            return {"ok": True, **self._state.runs[-1]}

        return {"ok": False, "error": f"Unknown query: {name}"}

    # ------------------------------------------------------------------ disconnect

    def disconnect(self) -> dict:
        """Tear down the session — release the namespace, optionally
        leave workdir on disk for inspection."""
        if self._state is None:
            return {"ok": True, "disconnected": True, "note": "no active session"}

        # Try to release DPF resources
        try:
            ns = self._state.namespace
            if ns.get("model") is not None:
                ns["model"] = None
            if ns.get("_data_sources") is not None:
                ns["_data_sources"] = None
        except Exception:
            pass

        wd = str(self._state.workdir)
        n_runs = len(self._state.runs)
        self._state = None
        return {
            "ok": True,
            "disconnected": True,
            "workdir": wd,
            "n_runs": n_runs,
        }


# --- helpers ---------------------------------------------------------------


def _summarize_keywords(deck) -> list[str]:
    """Return list of keyword class names in the deck."""
    out: list[str] = []
    try:
        for k in deck:
            out.append(type(k).__name__)
    except Exception:
        pass
    return out


def _coerce_result(value):
    """Best-effort conversion of arbitrary _result to JSON-safe type."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool, list, dict)):
        return value
    # Try common numpy / pandas forms
    try:
        import numpy as np
        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, np.generic):
            return value.item()
    except ImportError:
        pass
    try:
        import pandas as pd
        if isinstance(value, pd.DataFrame):
            return value.to_dict(orient="records")
        if isinstance(value, pd.Series):
            return value.to_dict()
    except ImportError:
        pass
    return repr(value)
