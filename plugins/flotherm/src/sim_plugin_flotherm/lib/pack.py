"""Read-only `.pack` archive inspection and lint."""
from __future__ import annotations

import zipfile
from pathlib import Path

from sim.driver import Diagnostic, LintResult


def pack_project_dir(pack: Path) -> str | None:
    """Return the top-level project directory name from inside a .pack ZIP."""
    try:
        with zipfile.ZipFile(pack) as z:
            names = z.namelist()
        dirs = {e.split("/")[0] for e in names if e.split("/")[0]}
        if dirs:
            return sorted(dirs)[0]
    except Exception:
        pass
    return None


def pack_project_name(proj_dir: str) -> str:
    """Extract short project name from directory (before the GUID dot)."""
    return proj_dir.split(".")[0] if "." in proj_dir else proj_dir


def lint_pack(pack: Path) -> LintResult:
    """Validate a .pack project archive."""
    diagnostics: list[Diagnostic] = []
    try:
        data = pack.read_bytes()
    except OSError as e:
        return LintResult(ok=False, diagnostics=[
            Diagnostic(level="error", message=f"Cannot read file: {e}")])
    if not data:
        return LintResult(ok=False, diagnostics=[
            Diagnostic(level="error", message="Pack file is empty")])
    try:
        with zipfile.ZipFile(pack) as z:
            names = z.namelist()
    except zipfile.BadZipFile as e:
        return LintResult(ok=False, diagnostics=[
            Diagnostic(level="error", message=f"Invalid ZIP/pack file: {e}")])
    top_level_dirs = {n.split("/")[0] for n in names if "/" in n}
    if not top_level_dirs:
        diagnostics.append(Diagnostic(
            level="warning", message="Pack file contains no project directory."))
    return LintResult(ok=True, diagnostics=diagnostics)
