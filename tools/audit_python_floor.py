#!/usr/bin/env python3
"""Audit sim repos before changing the supported Python floor.

This helper is intentionally read-only. It gathers the metadata and common
compatibility signals needed to decide whether lowering ``requires-python`` to
Python 3.9 is realistic, but it does not edit package metadata or workflows.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import shutil
import subprocess
import sys
import tokenize
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]


SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".pytest_basetemp",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
}


@dataclass(frozen=True)
class WorkflowVersion:
    workflow: str
    line: int
    value: str


@dataclass(frozen=True)
class Python39Blocker:
    path: str
    line: int
    kind: str
    text: str


@dataclass(frozen=True)
class RepoAudit:
    path: str
    name: str
    requires_python: str = ""
    python_classifiers: list[str] = field(default_factory=list)
    lock_requires_python: str = ""
    workflow_python_versions: list[WorkflowVersion] = field(default_factory=list)
    python39_blockers: list[Python39Blocker] = field(default_factory=list)


def load_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def pyproject_metadata(repo: Path) -> tuple[str, str, list[str]]:
    data = load_toml(repo / "pyproject.toml")
    project = data.get("project", {}) if isinstance(data, dict) else {}
    name = str(project.get("name") or repo.name)
    requires_python = str(project.get("requires-python") or "")
    classifiers = [
        str(item)
        for item in project.get("classifiers", [])
        if str(item).startswith("Programming Language :: Python :: 3")
    ]
    return name, requires_python, classifiers


def lock_requires_python(repo: Path) -> str:
    lock = repo / "uv.lock"
    if not lock.is_file():
        return ""
    for line in lock.read_text(encoding="utf-8", errors="replace").splitlines()[:20]:
        match = re.match(r'\s*requires-python\s*=\s*"([^"]+)"', line)
        if match:
            return match.group(1)
    return ""


def workflow_python_versions(repo: Path) -> list[WorkflowVersion]:
    workflows = repo / ".github" / "workflows"
    if not workflows.is_dir():
        return []

    versions: list[WorkflowVersion] = []
    for path in sorted(workflows.glob("*.y*ml")):
        for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw.split("#", 1)[0].strip()
            direct = re.search(r"python-version\s*:\s*['\"]?([^'\"\n]+)", line)
            if direct:
                versions.append(
                    WorkflowVersion(
                        workflow=path.relative_to(repo).as_posix(),
                        line=line_no,
                        value=direct.group(1).strip(),
                    )
                )
                continue

            matrix = re.search(r"\bpython\s*:\s*\[(.+)\]", line)
            if matrix:
                for value in re.findall(r"['\"]([^'\"]+)['\"]", matrix.group(1)):
                    versions.append(
                        WorkflowVersion(
                            workflow=path.relative_to(repo).as_posix(),
                            line=line_no,
                            value=value,
                        )
                    )
    return versions


def _python_files(repo: Path) -> list[Path]:
    out: list[Path] = []
    for path in repo.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.relative_to(repo).parts):
            continue
        out.append(path)
    return sorted(out)


def _has_tomllib_fallback(text: str) -> bool:
    return (
        "tomli as" in text
        and ("except ModuleNotFoundError" in text or "version_info" in text)
    )


def _has_future_annotations(text: str) -> bool:
    return bool(re.search(r"from\s+__future__\s+import\s+annotations", text))


def _code_tokens_by_line(text: str) -> dict[int, str]:
    tokens_by_line: dict[int, list[str]] = {}
    ignored = {
        tokenize.COMMENT,
        tokenize.DEDENT,
        tokenize.ENCODING,
        tokenize.ENDMARKER,
        tokenize.INDENT,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.STRING,
    }
    try:
        tokens = tokenize.generate_tokens(io.StringIO(text).readline)
        for token in tokens:
            if token.type in ignored:
                continue
            tokens_by_line.setdefault(token.start[0], []).append(token.string)
    except tokenize.TokenError:
        return {
            line_no: line.strip()
            for line_no, line in enumerate(text.splitlines(), 1)
            if line.strip()
        }
    return {line_no: " ".join(parts) for line_no, parts in tokens_by_line.items()}


def python39_blockers(repo: Path) -> list[Python39Blocker]:
    blockers: list[Python39Blocker] = []
    for path in _python_files(repo):
        rel = path.relative_to(repo).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        has_future_annotations = _has_future_annotations(text)
        has_tomllib_fallback = _has_tomllib_fallback(text)
        code_by_line = _code_tokens_by_line(text)

        for line_no, raw in enumerate(text.splitlines(), 1):
            code_line = code_by_line.get(line_no, "")
            if not code_line:
                continue
            line = raw.strip()
            kind = ""
            if code_line.startswith("match ") and "=" not in code_line.split(":", 1)[0]:
                kind = "match-statement"
            elif code_line.startswith("case "):
                kind = "match-case"
            elif re.search(r"@\s*dataclass\s*\(.*\bslots\s*=\s*True", code_line):
                kind = "dataclass-slots"
            elif re.search(r"\b(from\s+tomllib\s+import|import\s+tomllib\b)", code_line):
                if not has_tomllib_fallback:
                    kind = "tomllib-without-fallback"
            elif re.search(r"\btyping\s*\.\s*Self\b", code_line) or re.search(
                r"from\s+typing\s+import\s+.*\bSelf\b",
                code_line,
            ):
                kind = "typing-self"
            elif re.search(r"\bExceptionGroup\b", code_line):
                kind = "exception-group"
            elif not has_future_annotations and re.search(r"(->|:)\s*[^#=\n]*\|", code_line):
                kind = "pep604-runtime-union"

            if kind:
                blockers.append(
                    Python39Blocker(
                        path=rel,
                        line=line_no,
                        kind=kind,
                        text=line[:160],
                    )
                )
    return blockers


def audit_repo(repo: Path) -> RepoAudit:
    repo = repo.resolve()
    name, requires_python, classifiers = pyproject_metadata(repo)
    return RepoAudit(
        path=str(repo),
        name=name,
        requires_python=requires_python,
        python_classifiers=classifiers,
        lock_requires_python=lock_requires_python(repo),
        workflow_python_versions=workflow_python_versions(repo),
        python39_blockers=python39_blockers(repo),
    )


def default_repos(root: Path) -> list[Path]:
    parent = root.resolve().parent
    candidates = [root, parent / "sim-ltspice"]
    candidates.extend(sorted(parent.glob("sim-plugin-*")))
    return [path for path in candidates if (path / "pyproject.toml").is_file()]


def python_available(version: str) -> bool:
    commands: list[list[str]] = []
    if sys.platform == "win32" and shutil.which("py"):
        commands.append(["py", f"-{version}", "--version"])
    exe = shutil.which(f"python{version}")
    if exe:
        commands.append([exe, "--version"])
    if not commands:
        return False
    for command in commands:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=10)
        if proc.returncode == 0:
            return True
    return False


def summarize(audits: list[RepoAudit], *, check_python: str | None) -> dict[str, Any]:
    return {
        "repos": [asdict(audit) for audit in audits],
        "interpreter_checks": (
            {check_python: python_available(check_python)} if check_python else {}
        ),
    }


def render_text(report: dict[str, Any]) -> str:
    lines = ["Python floor audit", ""]
    for repo in report["repos"]:
        lines.append(f"- {repo['name']} ({repo['path']})")
        lines.append(f"  requires-python: {repo['requires_python'] or 'not declared'}")
        lines.append(f"  uv.lock requires-python: {repo['lock_requires_python'] or 'not found'}")
        classifiers = ", ".join(repo["python_classifiers"]) or "none"
        lines.append(f"  classifiers: {classifiers}")
        workflow_versions = repo["workflow_python_versions"]
        if workflow_versions:
            rendered = ", ".join(
                f"{item['workflow']}:{item['line']}={item['value']}"
                for item in workflow_versions
            )
        else:
            rendered = "none"
        lines.append(f"  workflow python versions: {rendered}")
        blockers = repo["python39_blockers"]
        if blockers:
            lines.append(f"  potential Python 3.9 blockers: {len(blockers)}")
            for item in blockers[:8]:
                lines.append(
                    f"    {item['path']}:{item['line']} {item['kind']}: {item['text']}"
                )
            if len(blockers) > 8:
                lines.append(f"    ... {len(blockers) - 8} more")
        else:
            lines.append("  potential Python 3.9 blockers: none found")
        lines.append("")

    checks = report.get("interpreter_checks") or {}
    if checks:
        lines.append("Interpreter checks")
        for version, available in checks.items():
            lines.append(f"- Python {version}: {'available' if available else 'not found'}")
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "repos",
        nargs="*",
        type=Path,
        help="Repository roots to audit. Defaults to sim-cli plus sibling sim repos.",
    )
    parser.add_argument(
        "--check-python",
        default="3.9",
        help="Interpreter version to probe, or empty string to skip.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    root = Path(__file__).resolve().parent.parent
    repos = args.repos or default_repos(root)
    audits = [audit_repo(path) for path in repos]
    report = summarize(audits, check_python=args.check_python or None)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render_text(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
