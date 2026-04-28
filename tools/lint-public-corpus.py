#!/usr/bin/env python3
"""Audit the public corpus for commercial-vendor name exposure.

Public sim-cli must not reveal that maintainers run commercial simulation
software. This script walks tracked source files and reports any occurrence
of vendor names from the forbidden list, with line context.

## Modes

- ``--warn`` (default): print a report and exit 0. Use during the migration
  while we still have legacy occurrences to clean up.
- ``--fail`` (post-Phase-3): exit non-zero on any unwhitelisted occurrence.
  CI runs this in fail mode to prevent regressions.

## Whitelist

A leading-comment marker on the same line allows a specific occurrence::

    # allow-vendor-name: <reason>      # in Python
    <!-- allow-vendor-name: <reason> --> # in markdown

The reason field is required and shown in the audit report. Use sparingly —
prefer rewriting the line over whitelisting.

A token whitelist (TOKEN_WHITELIST below) covers tokens that appear by virtue
of standing alone (e.g. "ltspice" until Phase 3 removes it; OSS solvers
shouldn't ever match anyway).

## Why
Per CLAUDE.md and memory ``feedback_compliance_hygiene_stance.md``: clean
public artifacts proactively. Framed as compliance hygiene, not evidence
destruction. No git history rewriting from this tool.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


# Vendor-name tokens to flag. Word-boundary matched, case-insensitive.
# Add new vendors here as we add their drivers.
FORBIDDEN_TOKENS: tuple[str, ...] = (
    "fluent",
    "pyfluent",      # Fluent's Python SDK — same exposure
    "comsol",
    "matlab",
    "simulink",
    "flotherm",
    "abaqus",
    "ansa",          # commercial mesh tool by Beta CAE
    "ltspice",       # whitelisted until Phase 3 — Analog Devices product
    "lsdyna",
    "ls-dyna",
    "ls_dyna",
    "lspp",          # LS-PrePost
    "cfx",
    "mapdl",
    "ansys",         # umbrella vendor name
    "hypermesh",
    "altair",        # vendor of Hypermesh / Hyperworks
    "icem",          # Ansys ICEM CFD
    "starccm",
    "star-ccm",
    "workbench",
    "tecplot",
    "ensight",
    "femfat",
)

# Tokens that are allowed to appear without per-line whitelist comments
# during the migration. Removed as their phase completes.
TOKEN_WHITELIST: set[str] = {
    "ltspice",        # public exception until Phase 3 — see plan §3
}

# Per-line allow comment patterns.
ALLOW_COMMENT_RE = re.compile(
    r"#\s*allow-vendor-name:\s*\S|<!--\s*allow-vendor-name:\s*\S"
)

# File extensions to scan. Skip binaries and lockfiles.
TEXT_EXTENSIONS = {
    ".py", ".md", ".txt", ".rst", ".yaml", ".yml", ".toml",
    ".json", ".sh", ".cfg", ".ini",
}

# Path globs to skip. uv.lock is huge and only contains pinned package
# names; tests fixtures may legitimately reference vendor strings as test
# inputs. Adjust carefully.
SKIP_PATH_PARTS = {
    "uv.lock",
    ".git",
    "__pycache__",
    ".venv",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    "node_modules",
}


@dataclass(frozen=True)
class Hit:
    path: Path
    line_no: int
    line: str
    token: str
    whitelisted: bool
    whitelist_reason: str = ""


def tracked_files(repo_root: Path) -> list[Path]:
    """Return git-tracked text files under repo_root."""
    proc = subprocess.run(
        ["git", "ls-files"],
        cwd=repo_root, capture_output=True, text=True, check=True,
    )
    files: list[Path] = []
    for raw in proc.stdout.splitlines():
        if not raw.strip():
            continue
        p = repo_root / raw
        if any(part in SKIP_PATH_PARTS for part in p.parts):
            continue
        if p.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        if not p.is_file():
            continue
        files.append(p)
    return files


def _build_pattern() -> re.Pattern[str]:
    # Word-boundary alternation; case-insensitive. Sort longest-first so
    # ``ls-dyna`` matches before ``ls`` would (defensive for future tokens).
    sorted_tokens = sorted(FORBIDDEN_TOKENS, key=len, reverse=True)
    alt = "|".join(re.escape(t) for t in sorted_tokens)
    return re.compile(rf"(?i)(?<![A-Za-z0-9_])({alt})(?![A-Za-z0-9_])")


def scan_file(path: Path, pattern: re.Pattern[str]) -> list[Hit]:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []

    hits: list[Hit] = []
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        # Cheap fast-path: skip lines that don't even contain a letter from
        # any token's first char. Saves regex work on long files.
        if not any(c.isalpha() for c in raw_line):
            continue
        for m in pattern.finditer(raw_line):
            token = m.group(1).lower()
            allowed = (
                token in TOKEN_WHITELIST
                or bool(ALLOW_COMMENT_RE.search(raw_line))
            )
            reason = ""
            if token in TOKEN_WHITELIST:
                reason = "TOKEN_WHITELIST"
            else:
                m2 = re.search(r"allow-vendor-name:\s*([^\s].*?)(?:-->|$)", raw_line)
                if m2:
                    reason = m2.group(1).strip()
            hits.append(Hit(
                path=path, line_no=line_no, line=raw_line.rstrip(),
                token=token, whitelisted=allowed, whitelist_reason=reason,
            ))
    return hits


def format_report(hits: list[Hit], repo_root: Path, *, show_allowed: bool) -> str:
    if not hits:
        return "Public corpus is clean.\n"

    flagged = [h for h in hits if not h.whitelisted]
    allowed = [h for h in hits if h.whitelisted]

    lines: list[str] = []
    lines.append(f"Found {len(hits)} occurrence(s) ({len(flagged)} flagged, {len(allowed)} allowed)")
    lines.append("")

    by_file: dict[Path, list[Hit]] = {}
    for h in flagged:
        by_file.setdefault(h.path, []).append(h)

    if flagged:
        lines.append(f"=== Flagged ({len(flagged)}) ===")
        for path, items in sorted(by_file.items()):
            rel = path.relative_to(repo_root)
            lines.append(f"\n{rel}:")
            for h in items:
                lines.append(f"  {h.line_no}:{h.token}: {h.line.strip()[:120]}")

    if show_allowed and allowed:
        lines.append("")
        lines.append(f"=== Allowed ({len(allowed)}) ===")
        by_file_a: dict[Path, list[Hit]] = {}
        for h in allowed:
            by_file_a.setdefault(h.path, []).append(h)
        for path, items in sorted(by_file_a.items()):
            rel = path.relative_to(repo_root)
            lines.append(f"\n{rel}:")
            for h in items:
                lines.append(f"  {h.line_no}:{h.token} ({h.whitelist_reason})")

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit public corpus for commercial-vendor name exposure.",
    )
    parser.add_argument(
        "--repo-root", default=".", type=Path,
        help="Repo root (default: cwd).",
    )
    parser.add_argument(
        "--fail", dest="fail_mode", action="store_true",
        help="Exit non-zero on flagged occurrences (post-Phase-3 mode).",
    )
    parser.add_argument(
        "--show-allowed", action="store_true",
        help="Also list whitelisted occurrences in the report.",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit machine-readable JSON instead of human report.",
    )
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    if not (repo_root / ".git").exists():
        print(f"error: {repo_root} is not a git repo", file=sys.stderr)
        return 2

    pattern = _build_pattern()
    hits: list[Hit] = []
    for path in tracked_files(repo_root):
        hits.extend(scan_file(path, pattern))

    flagged_count = sum(1 for h in hits if not h.whitelisted)

    if args.json:
        import json
        out = {
            "ok": flagged_count == 0,
            "total": len(hits),
            "flagged": flagged_count,
            "allowed": len(hits) - flagged_count,
            "hits": [
                {
                    "path": str(h.path.relative_to(repo_root)),
                    "line": h.line_no,
                    "token": h.token,
                    "whitelisted": h.whitelisted,
                    "reason": h.whitelist_reason,
                    "context": h.line.strip()[:200],
                }
                for h in hits
            ],
        }
        print(json.dumps(out, indent=2))
    else:
        print(format_report(hits, repo_root, show_allowed=args.show_allowed))

    if args.fail_mode and flagged_count > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
