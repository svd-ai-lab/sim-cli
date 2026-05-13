"""Migration shims for retired plugin installer commands.

``sim`` no longer installs or uninstalls plugin packages. Package mutation
belongs to the user's uv project; sim inspects installed packages, checks
drivers, and syncs bundled skills.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_PACKAGE_SPEC_RE = re.compile(
    r"^(sim-plugin-[A-Za-z0-9][A-Za-z0-9_.-]*)(?:\[[A-Za-z0-9_,.-]+\])?"
    r"(?:\s*(?:==|!=|~=|>=|<=|>|<)\s*[A-Za-z0-9.*+!_.-]+)?$"
)
_SHORT_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def _install_migration_message(source: str | None = None) -> str:
    base = (
        "sim plugin install is retired.\n\n"
        "Add plugins with uv instead:\n"
        "  uv add sim-cli-core <plugin-package-spec>\n"
        "  uv run sim plugin sync-skills --target .agents/skills --copy\n"
        "  uv run sim check <solver>"
    )

    if source:
        match = _PACKAGE_SPEC_RE.match(source.strip())
        if match:
            return (
                f"{base}\n\n"
                f"For this package spec, run:\n"
                f"  uv add sim-cli-core {source.strip()}"
            )
        if _SHORT_NAME_RE.match(source.strip()):
            return (
                f"{base}\n\n"
                "Short solver names are not package specs. Find the package spec in "
                "docs.svdailab.com/plugin-index or sim-plugin-index, then run:\n"
                "  uv add sim-cli-core <plugin-package-spec>"
            )

    return base


def _uninstall_migration_message(name: str | None = None) -> str:
    package = None
    if name:
        clean = name.strip()
        package = clean if clean.startswith("sim-plugin-") else f"sim-plugin-{clean}"
    command = f"  uv remove {package}" if package else "  uv remove <plugin-package-spec>"
    return (
        "sim plugin uninstall is retired.\n\n"
        "Remove plugin packages with uv instead:\n"
        f"{command}\n"
        "  uv run sim plugin sync-skills --target .agents/skills --copy"
    )


@dataclass
class InstallReport:
    ok: bool
    name: str | None
    source_kind: str
    pip_target: str
    pip_returncode: int
    pip_stdout: str
    pip_stderr: str
    sync_skills: dict[str, Any] | None = None
    error_code: str | None = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "name": self.name,
            "source_kind": self.source_kind,
            "pip_target": self.pip_target,
            "pip_returncode": self.pip_returncode,
            "pip_stdout": self.pip_stdout[-2000:],
            "pip_stderr": self.pip_stderr[-2000:],
            "sync_skills": self.sync_skills,
            "error_code": self.error_code,
            "message": self.message,
        }


def install_plugin(
    source: str,
    *,
    editable: bool = False,
    upgrade: bool = False,
    offline: bool = False,
    sync_target: Path | None = None,
    skip_sync: bool = False,
    python: str | None = None,
    extra_index_urls: list[str] | None = None,
) -> InstallReport:
    """Return migration guidance without invoking pip or uv pip."""
    _ = (editable, upgrade, offline, sync_target, skip_sync, python, extra_index_urls)
    match = _PACKAGE_SPEC_RE.match(source.strip())
    return InstallReport(
        ok=False,
        name=match.group(1) if match else None,
        source_kind="retired",
        pip_target=source,
        pip_returncode=-1,
        pip_stdout="",
        pip_stderr="",
        error_code="PLUGIN_INSTALL_RETIRED",
        message=_install_migration_message(source),
    )


def _default_skills_target() -> Path:
    """Where ``sync-skills`` writes by default.

    Uses ``./.claude/skills/`` if a ``.claude`` dir exists in cwd; falls
    back to ``~/.claude/skills/``. This matches Claude Code's discovery.
    """
    project = Path.cwd() / ".claude"
    if project.is_dir():
        return project / "skills"
    return Path.home() / ".claude" / "skills"


def uninstall_plugin(name: str, *, sync: bool = True,
                     python: str | None = None) -> dict[str, Any]:
    """Return migration guidance without invoking pip or uv pip."""
    _ = (sync, python)
    return {
        "ok": False,
        "name": name,
        "error_code": "PLUGIN_INSTALL_RETIRED",
        "message": _uninstall_migration_message(name),
    }


def bundle_plugins(names: list[str], output_dir: Path, *,
                   index_url: str | None = None) -> dict[str, Any]:
    """Return migration guidance for the removed bundle flow."""
    _ = index_url
    return {
        "ok": False,
        "output": str(output_dir),
        "fetched": [],
        "errors": [
            {
                "name": name,
                "error_code": "PLUGIN_INSTALL_RETIRED",
                "error": (
                    "sim plugin bundle is retired. Add plugin packages with "
                    "uv add sim-cli-core <plugin-package-spec> in the target "
                    "uv project instead."
                ),
            }
            for name in names
        ],
    }


__all__ = [
    "InstallReport",
    "install_plugin",
    "uninstall_plugin",
    "bundle_plugins",
    "_default_skills_target",
]
