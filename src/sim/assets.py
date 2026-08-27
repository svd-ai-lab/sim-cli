"""Read-only scanning of historical simulation assets with simparse."""
from __future__ import annotations

import importlib
import importlib.metadata
import os
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


SCAN_SCHEMA_VERSION = "sim.scan/v1"


def _display_path(path: Path, include_paths: bool) -> str:
    if include_paths:
        return str(path.resolve())
    return path.name or "."


def _path_key(path: Path) -> str:
    """Return a stable key used to avoid parsing overlapping roots twice."""
    return os.path.normcase(str(path.resolve()))


def _clean_error(exc: Exception, path: Path, include_paths: bool) -> str:
    """Keep parser diagnostics useful without leaking paths by default."""
    message = str(exc).strip() or type(exc).__name__
    if include_paths:
        return message

    display = _display_path(path, False)
    candidates = {
        str(path),
        str(path.resolve()),
        str(path).replace("\\", "/"),
        str(path.resolve()).replace("\\", "/"),
    }
    for candidate in sorted(candidates, key=len, reverse=True):
        if candidate:
            message = message.replace(candidate, display)
    return message


def _diagnostic(
    path: Path,
    error_code: str,
    message: str,
    include_paths: bool,
) -> dict[str, str]:
    return {
        "path": _display_path(path, include_paths),
        "error_code": error_code,
        "message": message[:280],
    }


def _iter_directory(path: Path, recursive: bool) -> tuple[list[Path], list[OSError]]:
    files: list[Path] = []
    errors: list[OSError] = []

    if not recursive:
        try:
            files.extend(entry for entry in path.iterdir() if entry.is_file())
        except OSError as exc:
            errors.append(exc)
        return sorted(files, key=lambda value: str(value).casefold()), errors

    def onerror(exc: OSError) -> None:
        errors.append(exc)

    for current, directory_names, file_names in os.walk(
        path,
        topdown=True,
        onerror=onerror,
        followlinks=False,
    ):
        directory_names.sort(key=str.casefold)
        file_names.sort(key=str.casefold)
        files.extend(Path(current, name) for name in file_names)
    return files, errors


def _load_simparse() -> tuple[Any, str]:
    module = importlib.import_module("simparse")
    try:
        version = importlib.metadata.version("simparse")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"
    return module, version


def _error_envelope(
    error_code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": False,
        "error_code": error_code,
        "message": message[:280],
    }
    if details:
        payload["details"] = details
    return payload


def scan_assets(
    paths: Iterable[Path],
    *,
    recursive: bool = True,
    include_paths: bool = False,
    full: bool = False,
    limit: int = 100,
    format_name: str = "auto",
) -> tuple[dict[str, Any], int]:
    """Scan files/directories and return ``(JSON payload, process exit code)``."""
    roots = tuple(Path(path) for path in paths)
    request = {
        "paths": [_display_path(path, include_paths) for path in roots],
        "recursive": recursive,
        "view": "full" if full else "summary",
        "include_paths": include_paths,
        "limit": limit,
        "format": format_name,
    }

    try:
        simparse, engine_version = _load_simparse()
    except Exception as exc:  # noqa: BLE001 - native extension load failures vary by platform
        return _error_envelope(
            "SIMPARSE_UNAVAILABLE",
            "simparse could not be loaded; reinstall sim-cli-core for this platform.",
            {"dependency": "simparse>=0.3.2,<0.4", "reason": str(exc)[:280]},
        ), 3

    assets: list[dict[str, Any]] = []
    diagnostics: list[dict[str, str]] = []
    seen: set[str] = set()

    def inspect_one(path: Path, *, explicit: bool, selected_format: str = "auto") -> None:
        key = _path_key(path)
        if key in seen:
            return
        seen.add(key)
        try:
            source_path = path.resolve() if include_paths else path
            asset = simparse.inspect(
                str(source_path),
                format=selected_format,
                include_paths=include_paths,
                summary=not full,
            )
        except Exception as exc:  # noqa: BLE001 - simparse exposes parse errors as RuntimeError
            reason = _clean_error(exc, path, include_paths)
            unsupported = reason.casefold().startswith((
                "unsupported file format",
                "unsupported format",
                "unknown format",
            ))
            if unsupported and not explicit:
                return
            code = "ASSET_FORMAT_UNSUPPORTED" if unsupported else "ASSET_SCAN_FAILED"
            prefix = "Unsupported simulation asset" if unsupported else "Could not parse simulation asset"
            diagnostics.append(_diagnostic(
                path,
                code,
                f"{prefix}: {_display_path(path, include_paths)}. {reason}",
                include_paths,
            ))
            return
        if isinstance(asset, dict):
            assets.append(asset)
        else:
            diagnostics.append(_diagnostic(
                path,
                "ASSET_SCAN_FAILED",
                f"simparse returned an invalid result for {_display_path(path, include_paths)}.",
                include_paths,
            ))

    for root in roots:
        if not root.exists():
            diagnostics.append(_diagnostic(
                root,
                "ASSET_PATH_NOT_FOUND",
                f"Asset path does not exist: {_display_path(root, include_paths)}.",
                include_paths,
            ))
            continue
        if root.is_file():
            inspect_one(root, explicit=True, selected_format=format_name)
            continue
        if not root.is_dir():
            diagnostics.append(_diagnostic(
                root,
                "ASSET_SCAN_FAILED",
                f"Asset path is not a regular file or directory: {_display_path(root, include_paths)}.",
                include_paths,
            ))
            continue
        if format_name != "auto":
            diagnostics.append(_diagnostic(
                root,
                "ASSET_FORMAT_UNSUPPORTED",
                "--format can only be used with explicit files, not directories.",
                include_paths,
            ))
            continue

        files, walk_errors = _iter_directory(root, recursive)
        for exc in walk_errors:
            diagnostics.append(_diagnostic(
                root,
                "ASSET_SCAN_FAILED",
                f"Could not read asset directory: {_clean_error(exc, root, include_paths)}",
                include_paths,
            ))
        for path in files:
            inspect_one(path, explicit=False)

    assets.sort(key=lambda item: (
        str(item.get("path", "")).casefold(),
        str(item.get("file_name", "")).casefold(),
        str(item.get("format", "")).casefold(),
    ))
    diagnostics.sort(key=lambda item: (item["path"].casefold(), item["error_code"]))

    parsed_ok = sum(bool(asset.get("ok")) for asset in assets)
    parsed_failed = len(assets) - parsed_ok
    formats = dict(sorted(Counter(
        str(asset.get("format", "unknown")) for asset in assets
    ).items()))
    asset_omitted = 0 if limit == 0 else max(0, len(assets) - limit)
    diagnostic_omitted = 0 if limit == 0 else max(0, len(diagnostics) - limit)
    returned_assets = assets if limit == 0 else assets[:limit]
    returned_diagnostics = diagnostics if limit == 0 else diagnostics[:limit]
    status = "partial" if diagnostics or parsed_failed else "ok"

    payload: dict[str, Any] = {
        "schema_version": SCAN_SCHEMA_VERSION,
        "ok": True,
        "status": status,
        "engine": {"name": "simparse", "version": engine_version},
        "request": request,
        "summary": {
            "roots": len(roots),
            "assets": len(assets),
            "ok": parsed_ok,
            "failed": parsed_failed + len(diagnostics),
            "formats": formats,
            "returned": len(returned_assets),
            "omitted": asset_omitted,
            "diagnostics": len(diagnostics),
            "diagnostics_omitted": diagnostic_omitted,
        },
        "assets": returned_assets,
        "diagnostics": returned_diagnostics,
        "truncated": bool(asset_omitted or diagnostic_omitted),
    }

    if not assets and diagnostics:
        codes = {diagnostic["error_code"] for diagnostic in diagnostics}
        user_error_codes = {"ASSET_FORMAT_UNSUPPORTED", "ASSET_PATH_NOT_FOUND"}
        error_code = next(iter(codes)) if len(codes) == 1 else "ASSET_SCAN_FAILED"
        message = {
            "ASSET_FORMAT_UNSUPPORTED": "No supported simulation asset could be parsed.",
            "ASSET_PATH_NOT_FOUND": "The requested simulation asset path does not exist.",
        }.get(
            error_code,
            "The simulation asset scan failed before any asset could be parsed.",
        )
        return _error_envelope(
            error_code,
            message,
            {key: value for key, value in payload.items() if key != "ok"},
        ), 2 if codes <= user_error_codes else 1

    return payload, 0


def render_scan(payload: dict[str, Any]) -> str:
    """Render one concise human-readable scan report."""
    if not payload.get("ok"):
        lines = [f"[sim] scan: {payload.get('message', 'failed')}"]
        details = payload.get("details", {})
        for diagnostic in details.get("diagnostics", []):
            lines.append(f"  ! {diagnostic['path']}: {diagnostic['message']}")
        return "\n".join(lines)

    summary = payload["summary"]
    lines = [
        f"[sim] scan: {summary['assets']} asset(s), "
        f"{summary['failed']} failure(s), status={payload['status']}"
    ]
    for asset in payload["assets"]:
        state = "ok" if asset.get("ok") else "failed"
        lines.append(
            f"  {asset.get('format', 'unknown'):<20} "
            f"{asset.get('file_name', '?')}  [{state}]"
        )
    for diagnostic in payload["diagnostics"]:
        lines.append(f"  ! {diagnostic['path']}: {diagnostic['message']}")
    if payload.get("truncated"):
        lines.append(
            f"  ... {summary['omitted']} asset(s) and "
            f"{summary['diagnostics_omitted']} diagnostic(s) omitted"
        )
    return "\n".join(lines)
