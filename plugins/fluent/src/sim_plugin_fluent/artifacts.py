"""Fluent artifact classification and lightweight file inventory helpers."""
from __future__ import annotations

from pathlib import Path


FLUENT_ARTIFACT_ROLES: dict[str, str] = {
    ".cas.h5": "fluent-case",
    ".cas": "fluent-case",
    ".dat.h5": "fluent-data",
    ".dat": "fluent-data",
    ".msh.h5": "fluent-mesh",
    ".msh": "fluent-mesh",
    ".trn": "fluent-transcript",
    ".jou": "fluent-journal",
    ".log": "fluent-log",
    ".pdf": "pdf-table",
    ".fla": "flamelet",
    ".csv": "tabular-data",
    ".png": "image",
    ".json": "result-json",
}


def classify_fluent_artifact(path: str | Path, current_role: str = "artifact") -> str:
    """Return the Fluent-specific artifact role for *path* when known."""
    low = str(path).lower()
    for suffix, role in sorted(FLUENT_ARTIFACT_ROLES.items(), key=lambda item: -len(item[0])):
        if low.endswith(suffix):
            return role
    return current_role


def list_fluent_files(root: str | Path, *, max_files: int = 100) -> list[dict]:
    """Return a bounded inventory of Fluent-relevant files below *root*."""
    base = Path(root)
    if not base.is_dir():
        return []

    rows: list[dict] = []
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        role = classify_fluent_artifact(path, "")
        if not role:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        rows.append(
            {
                "path": str(path),
                "relative_path": str(path.relative_to(base)).replace("\\", "/"),
                "role": role,
                "size_bytes": stat.st_size,
                "modified_at": stat.st_mtime,
            }
        )

    rows.sort(key=lambda item: (item["modified_at"], item["relative_path"]), reverse=True)
    return rows[:max_files]
