"""Audit logging for Java Shell submissions."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .shell import JavaShellChannel


def default_audit_dir(cwd: str | Path | None = None) -> Path:
    base = Path(cwd) if cwd is not None else Path.cwd()
    return base / ".sim" / "comsol-desktop-attach"


def code_hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def capped_preview(code: str, limit: int = 200) -> str:
    compact = code.replace("\r\n", "\n").strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "..."


def append_audit(
    channel: JavaShellChannel,
    code: str,
    status: str,
    *,
    audit_dir: str | Path | None = None,
) -> Path:
    out_dir = Path(audit_dir) if audit_dir is not None else default_audit_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "audit.jsonl"
    target = channel.target
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "desktop_pid": target.desktop_pid,
        "hwnd": target.hwnd,
        "window_title": target.window_title,
        "target_id": target.target_id,
        "exec_language": "java-shell",
        "code_sha256": code_hash(code),
        "code_preview": capped_preview(code),
        "status": status,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=True) + "\n")
    return path
