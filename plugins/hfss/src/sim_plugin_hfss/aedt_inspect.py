"""Best-effort offline inspection for AEDT project files.

This module intentionally does not import PyAEDT or launch AEDT. It is a
format-sniffing helper for quick triage on machines where the solver is not
available. Treat parsed project internals as hints until calibrated against a
live AEDT/PyAEDT summary from the same file.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_MAX_BYTES = 64 * 1024 * 1024
_MAX_RESULT_FILES = 5000

_BEGIN_RE = re.compile(r"^\s*\$begin\s+['\"]?(?P<name>[^'\"\r\n]+?)['\"]?\s*$", re.MULTILINE)
_END_RE = re.compile(r"^\s*\$end\s+['\"]?(?P<name>[^'\"\r\n]+?)['\"]?\s*$", re.MULTILINE)
_SAFE_NAME_RE = re.compile(r"^[A-Za-z_$][\w$]*$")
_NUMBERISH_RE = re.compile(r"[-+]?\d")
_FREQ_RE = re.compile(r"Frequency\s+([-+]?\d+(?:\.\d+)?)", re.IGNORECASE)
_SUCCESS_RE = re.compile(r"Success\s+([01])", re.IGNORECASE)

_DESIGN_MARKERS = (
    "designtype",
    "solutiontype",
    "designsettings",
    "boundarysetup",
    "analysissetup",
    "hfss",
    "icepak",
    "q3d",
    "maxwell",
)
_DESIGN_TYPES = (
    "HFSS 3D Layout",
    "HFSS",
    "Circuit Design",
    "Q3D Extractor",
    "Q2D Extractor",
    "Maxwell 3D",
    "Maxwell 2D",
    "Icepak",
)
_DESIGN_MODEL_BLOCK_TYPES = {
    "hfssmodel": "HFSS",
    "hfss3dlayoutmodel": "HFSS 3D Layout",
    "q3dmodel": "Q3D Extractor",
    "q2dmodel": "Q2D Extractor",
    "maxwell3dmodel": "Maxwell 3D",
    "maxwell2dmodel": "Maxwell 2D",
    "icepakmodel": "Icepak",
    "circuitmodel": "Circuit Design",
    "nexximmodel": "Circuit Design",
}
_VARIABLE_STOPWORDS = {
    "name",
    "type",
    "unit",
    "value",
    "objects",
    "faces",
    "edges",
    "terminals",
    "material",
    "frequency",
    "rangeend",
    "rangestart",
    "rangestep",
}


@dataclass(frozen=True)
class _Block:
    name: str
    start: int
    end: int
    start_line: int
    end_line: int


def inspect_aedt(path: str | Path, *, max_bytes: int = DEFAULT_MAX_BYTES) -> dict[str, Any]:
    """Inspect an ``.aedt`` or zip-packaged ``.aedtz`` file without AEDT.

    Parameters
    ----------
    path:
        AEDT project path.
    max_bytes:
        Maximum bytes to read from the project payload. Large project files are
        truncated rather than fully loaded.
    """
    project_path = Path(path)
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if not project_path.exists():
        return {
            "ok": False,
            "error_code": "FILE_NOT_FOUND",
            "path": str(project_path),
            "message": "AEDT project file was not found.",
        }

    warnings: list[str] = []
    payload, source = _read_project_payload(project_path, max_bytes=max_bytes, warnings=warnings)
    text, encoding, text_warning = _decode_payload(payload)
    if text_warning:
        warnings.append(text_warning)

    blocks = _parse_blocks(text)
    project = {
        "name": _project_name(project_path, text),
        "version_hint": _version_hint(text),
    }

    designs = _extract_designs(text, blocks)
    results = _inspect_results_sidecars(project_path)
    confidence = _confidence_summary(designs, text, source["truncated"])

    if not designs:
        warnings.append("No AEDT design blocks were recognized by the offline scanner.")
    if source["truncated"]:
        warnings.append("Project payload was truncated; later design data may be missing.")

    return {
        "ok": True,
        "path": str(project_path),
        "format": source["format"],
        "file": _file_summary(project_path),
        "source": source,
        "encoding": encoding,
        "project": project,
        "design_count": len(designs),
        "designs": designs,
        "results": results,
        "confidence": confidence,
        "warnings": warnings,
        "limits": [
            "Offline AEDT inspection is best-effort and regex/section based.",
            "It does not execute the model, read mesh connectivity, or extract field data.",
            "Geometry, boundary semantics, and solver setup details must be validated with AEDT/PyAEDT when accuracy matters.",
        ],
    }


def _read_project_payload(path: Path, *, max_bytes: int, warnings: list[str]) -> tuple[bytes, dict[str, Any]]:
    source: dict[str, Any] = {
        "format": "aedtz_zip" if zipfile.is_zipfile(path) else path.suffix.lower().lstrip(".") or "unknown",
        "max_bytes": max_bytes,
        "truncated": False,
        "archive_members": [],
        "aedt_member": None,
    }

    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            source["archive_members"] = [
                {"name": info.filename, "size_bytes": info.file_size}
                for info in infos[:200]
            ]
            candidates = [info for info in infos if info.filename.lower().endswith(".aedt")]
            if not candidates:
                warnings.append("Archive did not contain an .aedt member; scanning the largest text-like member instead.")
                candidates = sorted(infos, key=lambda info: info.file_size, reverse=True)[:1]
            if not candidates:
                return b"", source
            member = sorted(candidates, key=lambda info: info.file_size, reverse=True)[0]
            source["aedt_member"] = member.filename
            with zf.open(member) as fp:
                payload = fp.read(max_bytes + 1)
    else:
        with path.open("rb") as fp:
            payload = fp.read(max_bytes + 1)

    if len(payload) > max_bytes:
        source["truncated"] = True
        payload = payload[:max_bytes]
    source["payload_bytes"] = len(payload)
    return payload, source


def _decode_payload(payload: bytes) -> tuple[str, str, str | None]:
    if not payload:
        return "", "empty", None

    if payload.startswith(b"\xff\xfe") or payload.startswith(b"\xfe\xff"):
        encodings = ("utf-16", "utf-8-sig", "latin-1")
    elif payload[:4096].count(b"\x00") > 20:
        encodings = ("utf-16-le", "utf-16", "utf-8-sig", "latin-1")
    else:
        encodings = ("utf-8-sig", "utf-16", "latin-1")

    for encoding in encodings:
        try:
            text = payload.decode(encoding)
        except UnicodeDecodeError:
            continue
        if _text_score(text) > 0.65 or encoding == "latin-1":
            return text.replace("\x00", ""), encoding, None

    text = payload.decode("utf-8", errors="replace").replace("\x00", "")
    return text, "utf-8-replace", "Project payload required replacement decoding."


def _text_score(text: str) -> float:
    if not text:
        return 1.0
    sample = text[:4096]
    printable = sum(1 for ch in sample if ch in "\r\n\t" or 32 <= ord(ch) < 127)
    return printable / max(len(sample), 1)


def _file_summary(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "suffix": path.suffix.lower(),
    }


def _project_name(path: Path, text: str) -> str:
    return (
        _first_match(
            text,
            [
                r"\bProjectName\b\s*(?:=|:=)\s*['\"]([^'\"]+)",
                r"\bName\b\s*:=\s*['\"]([^'\"]+)['\"].{0,80}\bProject\b",
            ],
        )
        or path.stem
    )


def _parse_blocks(text: str) -> list[_Block]:
    events: list[tuple[int, int, str, str]] = []
    line_starts = _line_starts(text)
    for match in _BEGIN_RE.finditer(text):
        events.append((match.start(), _line_for_offset(line_starts, match.start()), "begin", match.group("name").strip()))
    for match in _END_RE.finditer(text):
        events.append((match.start(), _line_for_offset(line_starts, match.start()), "end", match.group("name").strip()))
    events.sort(key=lambda item: item[0])

    blocks: list[_Block] = []
    stack: list[tuple[str, int, int]] = []
    for offset, line_no, kind, name in events:
        if kind == "begin":
            stack.append((name, offset, line_no))
            continue
        if not stack:
            continue
        start_name, start, start_line = stack.pop()
        blocks.append(_Block(start_name, start, offset, start_line, line_no))
    return blocks


def _line_starts(text: str) -> list[int]:
    starts = [0]
    for match in re.finditer("\n", text):
        starts.append(match.end())
    return starts


def _line_for_offset(starts: list[int], offset: int) -> int:
    lo = 0
    hi = len(starts)
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if starts[mid] <= offset:
            lo = mid
        else:
            hi = mid
    return lo + 1


def _extract_designs(text: str, blocks: list[_Block]) -> list[dict[str, Any]]:
    candidates = _candidate_design_blocks(text, blocks)
    if not candidates:
        fallback_names = _dedupe(re.findall(r"\b(?:HFSS|Q3D|Q2D|Maxwell|Icepak|Circuit)Design\d+\b", text))
        return [_design_summary(name, text, 1, text.count("\n") + 1) for name in fallback_names]

    designs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for block in candidates:
        body = text[block.start:block.end]
        name = _design_name(block.name, body)
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        designs.append(_design_summary(name, body, block.start_line, block.end_line, block_name=block.name))
    return designs


def _candidate_design_blocks(text: str, blocks: list[_Block]) -> list[_Block]:
    model_candidates: list[_Block] = []
    preview_candidates: list[_Block] = []
    for block in sorted(blocks, key=lambda item: item.end - item.start, reverse=True):
        body = text[block.start:block.end]
        block_key = _block_key(block.name)
        if _looks_like_container(block.name):
            continue
        if block_key in _DESIGN_MODEL_BLOCK_TYPES:
            model_candidates.append(block)
            continue
        if (
            re.search(r"^\s*DesignID\s*=", body, re.MULTILINE)
            and re.search(r"^\s*Name\s*=", body, re.MULTILINE)
            and re.search(r"^\s*SolutionType\s*=", body, re.MULTILINE)
        ):
            model_candidates.append(block)
            continue
        if block_key == "designinfo" and "DesignName" in body and "Factory" in body:
            preview_candidates.append(block)
    if model_candidates:
        return _remove_nested_candidates(model_candidates)
    return _remove_nested_candidates(preview_candidates)


def _remove_nested_candidates(candidates: list[_Block]) -> list[_Block]:
    selected: list[_Block] = []
    for block in sorted(candidates, key=lambda item: item.start):
        if any(parent.start <= block.start and block.end <= parent.end for parent in selected):
            continue
        selected.append(block)
    return selected


def _looks_like_container(name: str) -> bool:
    lowered = name.lower()
    return lowered in {"ansoftproject", "project", "definitions"} or lowered.endswith("definitions")


def _block_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _design_name(block_name: str, body: str) -> str:
    return (
        _first_match(
            body,
            [
                r"\bDesignName\b\s*(?:=|:=)\s*['\"]([^'\"]+)",
                r"(?m)^\s*Name\s*=\s*['\"]([^'\"]+)",
                r"\bName\b\s*:=\s*['\"]([^'\"]+)['\"].{0,120}\bDesign\b",
            ],
        )
        or block_name
    )


def _design_summary(name: str, body: str, start_line: int, end_line: int, *, block_name: str = "") -> dict[str, Any]:
    setups = _extract_named_items(
        body,
        [
            r"\bSetupName\b\s*(?:=|:=)\s*['\"]([^'\"]+)",
            r"\bNAME:([^'\",\)\r\n]*Setup[^'\",\)\r\n]*)",
            r"['\"]([^'\"\r\n]*Setup\d+[^'\"\r\n]*)['\"]",
        ],
    )
    sweeps = _extract_named_items(
        body,
        [
            r"\bSweepName\b\s*(?:=|:=)\s*['\"]([^'\"]+)",
            r"\bNAME:([^'\",\)\r\n]*Sweep[^'\",\)\r\n]*)",
            r"['\"]([^'\"\r\n]*Sweep\d+[^'\"\r\n]*)['\"]",
        ],
    )
    excitations = _extract_named_items(
        body,
        [
            r"\bExcitationName\b\s*(?:=|:=)\s*['\"]([^'\"]+)",
            r"\bNAME:([^'\",\)\r\n]*(?:Port|Terminal|Excitation)[^'\",\)\r\n]*)",
            r"\$begin ['\"]([^'\"\r\n]*(?:LumpedPort|WavePort|Terminal)[^'\"\r\n]*)['\"]",
        ],
    )
    boundaries = _extract_named_items(
        body,
        [
            r"\bBoundaryName\b\s*(?:=|:=)\s*['\"]([^'\"]+)",
            r"\bNAME:([^'\",\)\r\n]*(?:Radiation|PerfectE|PerfectH|Impedance|Boundary|Finite Conductivity)[^'\",\)\r\n]*)",
            r"['\"]([^'\"\r\n]*(?:Radiation|PerfectE|PerfectH|Impedance|Finite Conductivity)[^'\"\r\n]*)['\"]",
        ],
    )
    return {
        "name": name,
        "type": _design_type(body, block_name=block_name),
        "solution_type": _first_match(
            body,
            [
                r"\bSolutionType\b\s*(?:=|:=)\s*['\"]?([^'\"\r\n,\)]+)",
                r"\bSolution\s+Type\b\s*(?:=|:=)\s*['\"]?([^'\"\r\n,\)]+)",
            ],
        ),
        "line_range": [start_line, end_line],
        "variables": _extract_variables(body),
        "setups": setups,
        "sweeps": sweeps,
        "excitations": excitations,
        "boundaries": boundaries,
        "materials": _extract_materials(body),
        "objects": _extract_objects(body),
        "confidence": {
            "identity": "medium" if name else "low",
            "type": "medium" if _design_type(body, block_name=block_name) else "low",
            "variables": "medium",
            "setups": "low" if not setups else "medium",
            "boundaries": "low" if not (boundaries or excitations) else "medium",
            "geometry": "low",
        },
}


def _design_type(body: str, *, block_name: str = "") -> str | None:
    block_type = _DESIGN_MODEL_BLOCK_TYPES.get(_block_key(block_name))
    if block_type:
        return block_type
    explicit = _first_match(
        body,
        [
            r"\bDesignType\b\s*(?:=|:=)\s*['\"]?([^'\"\r\n,\)]+)",
            r"\bDesign\s+Type\b\s*(?:=|:=)\s*['\"]?([^'\"\r\n,\)]+)",
            r"\bFactory\b\s*=\s*['\"]([^'\"]+)",
        ],
    )
    if explicit:
        return explicit.strip()
    lowered = body.lower()
    for design_type in _DESIGN_TYPES:
        if design_type.lower() in lowered:
            return design_type
    return None


def _extract_variables(body: str) -> dict[str, str]:
    variables: dict[str, str] = {}

    for match in re.finditer(
        r"VariableProp\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"][^'\"]*['\"]\s*,\s*['\"][^'\"]*['\"]\s*,\s*['\"]([^'\"]*)['\"]",
        body,
        re.DOTALL,
    ):
        variables[match.group(1).strip()] = match.group(2).strip()

    for match in re.finditer(r"VariableProp\(\s*['\"]([^'\"]+)['\"](?P<body>.*?)\)", body, re.DOTALL):
        name = match.group(1).strip()
        value = _first_match(
            match.group("body"),
            [
                r"\bValue:=['\"]\s*,\s*['\"]([^'\"]+)",
                r"\bValue:=\s*['\"]([^'\"]+)",
                r"\bValue\b\s*(?:=|:=)\s*['\"]([^'\"]+)",
            ],
        )
        if name and value is not None:
            variables.setdefault(name, value.strip())

    ordered_names = set(_extract_variable_orders(body))
    for match in re.finditer(
        r"^\s*(?P<name>[$A-Za-z_][\w$]*)\s*(?:=|:=)\s*['\"]?(?P<value>[^'\"\r\n]+)",
        body,
        re.MULTILINE,
    ):
        name = match.group("name").strip()
        value = match.group("value").strip().rstrip(",")
        if name in ordered_names and _is_probable_variable(name, value):
            variables.setdefault(name, value)

    return dict(sorted(variables.items()))


def _extract_variable_orders(body: str) -> list[str]:
    names: list[str] = []
    for match in re.finditer(r"VariableOrders\[\d+:\s*(.*?)\]", body, re.DOTALL):
        names.extend(re.findall(r"['\"]([^'\"]+)['\"]", match.group(1)))
    return _dedupe(names)


def _is_probable_variable(name: str, value: str) -> bool:
    lowered = name.lower()
    if lowered in _VARIABLE_STOPWORDS or not _SAFE_NAME_RE.match(name):
        return False
    if not value or len(value) > 200:
        return False
    return bool(_NUMBERISH_RE.search(value)) or any(token in value for token in ("$", "+", "-", "*", "/", "sqrt", "sin", "cos"))


def _extract_named_items(body: str, patterns: list[str]) -> list[str]:
    values: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, body, re.IGNORECASE):
            value = match.group(1).strip().strip("'\"")
            if _good_item_name(value):
                values.append(value)
    return _dedupe(values)


def _extract_materials(body: str) -> list[str]:
    return _extract_named_items(
        body,
        [
            r"\bMaterial(?:Name)?\b\s*(?:=|:=)\s*['\"]([^'\"]+)",
            r"\bMaterialValue\b\s*=\s*['\"]\"?([^'\"\r\n]+)",
            r"\bmaterial\b\s*=\s*['\"]([^'\"]+)",
        ],
    )


def _extract_objects(body: str) -> list[str]:
    values = _extract_named_items(
        body,
        [
            r"\bObjectName\b\s*(?:=|:=)\s*['\"]([^'\"]+)",
            r"\bObjects\b\s*(?:=|:=)\s*['\"]([^'\"]+)",
            r"\bDrawings\[\d+\]\s*(?:=|:=)\s*['\"]([^'\"]+)",
        ],
    )
    for match in re.finditer(r"\$begin 'GeometryPart'(?P<body>.*?)\$end 'GeometryPart'", body, re.DOTALL):
        name = _first_match(match.group("body"), [r"(?m)^\s*Name\s*=\s*['\"]([^'\"]+)"])
        if name:
            values.append(name)
    return _dedupe(values)


def _good_item_name(value: str) -> bool:
    if not value or len(value) > 120:
        return False
    lowered = value.lower()
    if lowered in {"name", "value", "type", "objects", "faces", "edges"}:
        return False
    return True


def _inspect_results_sidecars(path: Path) -> dict[str, Any]:
    lock_path = Path(str(path) + ".lock")
    results_dir = Path(str(path) + "results")
    summary: dict[str, Any] = {
        "lock_file": {
            "path": str(lock_path),
            "exists": lock_path.exists(),
        },
        "results_dir": {
            "path": str(results_dir),
            "exists": results_dir.exists(),
            "size_bytes": 0,
            "file_count": 0,
            "truncated": False,
        },
        "solution_progress": {
            "su_file_count": 0,
            "success_count": 0,
            "frequencies_ghz": [],
            "latest": None,
        },
    }
    if not results_dir.exists() or not results_dir.is_dir():
        return summary

    files_seen = 0
    size_bytes = 0
    su_records: list[dict[str, Any]] = []
    for child in results_dir.rglob("*"):
        if not child.is_file():
            continue
        files_seen += 1
        if files_seen > _MAX_RESULT_FILES:
            summary["results_dir"]["truncated"] = True
            break
        try:
            size_bytes += child.stat().st_size
        except OSError:
            continue
        if child.name.endswith("_SU.txt"):
            record = _read_su_file(child)
            if record:
                su_records.append(record)

    summary["results_dir"].update({"size_bytes": size_bytes, "file_count": files_seen})
    su_records.sort(key=lambda item: item.get("modified_at") or "")
    summary["solution_progress"] = {
        "su_file_count": len(su_records),
        "success_count": sum(1 for item in su_records if item.get("success") is True),
        "frequencies_ghz": [
            item["frequency_ghz"]
            for item in su_records
            if item.get("frequency_ghz") is not None
        ],
        "latest": su_records[-1] if su_records else None,
    }
    return summary


def _read_su_file(path: Path) -> dict[str, Any] | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        stat = path.stat()
    except OSError:
        return None
    frequency = None
    match = _FREQ_RE.search(text)
    if match:
        frequency = float(match.group(1)) / 1e9
    success = None
    match = _SUCCESS_RE.search(text)
    if match:
        success = match.group(1) == "1"
    return {
        "path": str(path),
        "frequency_ghz": frequency,
        "success": success,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


def _confidence_summary(designs: list[dict[str, Any]], text: str, truncated: bool) -> dict[str, str]:
    has_sections = "$begin" in text and "$end" in text
    return {
        "file_sniff": "medium" if text else "low",
        "section_tree": "medium" if has_sections else "low",
        "design_identity": "medium" if designs else "low",
        "design_details": "low" if truncated else "medium" if designs else "low",
        "results_sidecar": "high",
    }


def _first_match(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
    return None


def _version_hint(text: str) -> str | None:
    explicit = _first_match(
        text,
        [
            r"\b(?:ProductVersion|AEDTVersion|AedtVersion)\b\s*(?:=|:=)\s*['\"]?([^'\"\s,\)]+)",
            r"\bAnsys\s+Electronics\s+Desktop\s+([0-9]{4}\.[0-9])",
        ],
    )
    if explicit:
        return explicit
    match = re.search(r"\bVersion\(\s*(20\d{2})\s*,\s*(\d+)\s*\)", text)
    if match:
        return f"{match.group(1)}.{match.group(2)}"
    return None


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = " ".join(value.strip().split())
        key = cleaned.lower()
        if cleaned and key not in seen:
            seen.add(key)
            out.append(cleaned)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Best-effort offline AEDT project inspection.")
    parser.add_argument("project", help="Path to a .aedt or .aedtz file.")
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=DEFAULT_MAX_BYTES,
        help=f"Maximum project payload bytes to scan (default: {DEFAULT_MAX_BYTES}).",
    )
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON.")
    args = parser.parse_args(argv)

    try:
        payload = inspect_aedt(args.project, max_bytes=args.max_bytes)
    except Exception as exc:  # pragma: no cover - CLI guardrail
        payload = {
            "ok": False,
            "error_code": "INSPECT_FAILED",
            "path": args.project,
            "message": f"{type(exc).__name__}: {exc}",
        }
        print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
        return 2

    indent = None if args.compact else 2
    print(json.dumps(payload, ensure_ascii=False, indent=indent))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
