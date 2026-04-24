"""Global run history — append-only JSON Lines at ~/.sim/history.jsonl.

Replaces the per-project `.sim/runs/NNN.json` layout used by `RunStore`.
Every `sim run` (one-shot) and every `/exec` call through a live session
appends one record here. The record shape is pinned by
`docs/architecture/multi-session-and-config.md` §2 — all fields are
always present (nulls / empty strings for unused dimensions).

Filtering is the reader's job — callers pass `cwd`, `solver`, or
`session_id` to narrow the view. The file itself is a pure append log.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any, Iterable

from sim import config as _cfg


SCHEMA_FIELDS = (
    "ts",
    "cwd",
    "session_id",
    "solver",
    "run_id",
    "kind",
    "label",
    "ok",
    "duration_ms",
    "error",
    "parsed_output",
)


def _now_utc_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_file() -> Path:
    path = _cfg.history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.touch()
    return path


def _normalize(record: dict[str, Any]) -> dict[str, Any]:
    """Fill in missing schema fields so every line has the same columns."""
    out = {
        "ts": record.get("ts") or _now_utc_iso(),
        "cwd": record.get("cwd") or str(Path.cwd()),
        "session_id": record.get("session_id") or "",
        "solver": record.get("solver") or "",
        "run_id": record.get("run_id") or "",
        "kind": record.get("kind") or "run",
        "label": record.get("label") or "",
        "ok": bool(record.get("ok", False)),
        "duration_ms": int(record.get("duration_ms", 0) or 0),
        "error": record.get("error"),
    }
    # Parsed output is optional but commonly present for one-shot runs.
    if "parsed_output" in record:
        out["parsed_output"] = record["parsed_output"]
    # Preserve script path for one-shot runs so `sim logs` can show it.
    if "script" in record:
        out["script"] = record["script"]
    return out


def append(record: dict[str, Any]) -> str:
    """Append one record and return its `run_id` (allocates if missing)."""
    rec = _normalize(record)
    if not rec["run_id"]:
        rec["run_id"] = _next_run_id()
    path = _ensure_file()
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    return rec["run_id"]


def _next_run_id() -> str:
    """Scan existing records for max numeric id and return id+1.

    Kept simple — for throughput-bound workflows we'd move to UUIDs, but
    at human-CLI pace monotonic ints are more readable in `sim logs`.
    """
    records = _read_raw()
    max_n = 0
    for r in records:
        rid = r.get("run_id", "")
        try:
            n = int(rid)
        except (TypeError, ValueError):
            continue
        if n > max_n:
            max_n = n
    return f"{max_n + 1:03d}"


def _read_raw() -> list[dict]:
    path = _cfg.history_path()
    if not path.is_file():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # skip corrupt lines rather than fail
    return out


def read(
    *,
    cwd: str | Path | None = None,
    solver: str | None = None,
    session_id: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Read records with optional filters. Most recent first."""
    records = _read_raw()
    if cwd is not None:
        cwd_s = str(Path(cwd).resolve())
        records = [r for r in records if _resolve_cwd(r.get("cwd", "")) == cwd_s]
    if solver is not None:
        records = [r for r in records if r.get("solver") == solver]
    if session_id is not None:
        records = [r for r in records if r.get("session_id") == session_id]
    # Newest first: reverse write order.
    records = list(reversed(records))
    if limit is not None:
        records = records[:limit]
    return records


def _resolve_cwd(raw: str) -> str:
    """Best-effort resolve of a stored cwd for comparison. Missing path stays as-is."""
    if not raw:
        return ""
    try:
        return str(Path(raw).resolve())
    except OSError:
        return raw


def get_by_id(run_id: str, *, cwd: str | Path | None = None) -> dict | None:
    """Look up a single record by id. `last` returns the most recent record.

    When `cwd` is given, filters to that project scope (both for `last`
    and for numeric ids). Returns None if nothing matches.
    """
    records = read(cwd=cwd)
    if not records:
        return None
    if run_id == "last":
        return records[0]
    for r in records:
        if r.get("run_id") == run_id:
            return r
    return None


def iter_all() -> Iterable[dict]:
    """Iterate every record, in write order. Useful for tools that stream."""
    yield from _read_raw()
