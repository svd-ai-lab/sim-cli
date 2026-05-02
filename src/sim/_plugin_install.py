"""Install / uninstall / bundle plugins.

The `sim plugin` group's mutating commands route through here. Discovery
and validation live in :mod:`sim.plugins`; this module only handles the
install pipeline.

A `<source>` argument can be any of:

* ``sim-plugin-<name>`` / ``sim-plugin-<name>==<version>`` — exact pip
  package spec.
* ``https://...whl`` / ``https://...tar.gz`` — direct wheel/sdist URL.
* ``./path/to/dir`` — local plugin source directory.
* ``./path/to/wheel.whl`` / ``./path/to/sdist.tar.gz`` — local artifact.
* ``git+https://...`` / ``git+ssh://...`` — git URL.

The resolver classifies the source with no network calls and no plugin
registry lookup. Then a single ``pip install`` invocation does the work.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ── Source resolution ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class ResolvedSource:
    """One install source classified into a canonical kind."""
    kind: str
    raw: str            # the original argument
    name: str | None = None
    version: str | None = None
    pip_target: str = ""   # what pip install gets handed
    extras: dict[str, Any] = field(default_factory=dict)


_SHORT_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_SIM_PLUGIN_PACKAGE_RE = re.compile(
    r"^(sim-plugin-[A-Za-z0-9][A-Za-z0-9_.-]*)(?:\[[A-Za-z0-9_,.-]+\])?"
    r"(?:\s*(?:==|!=|~=|>=|<=|>|<)\s*[A-Za-z0-9.*+!_.-]+)?$"
)
_VERSION_PIN_RE = re.compile(r"(?:==|!=|~=|>=|<=|>|<)\s*(.+)$")


def _short_name_error(name: str) -> str:
    return (
        f"{name!r} is a catalog name, not an explicit plugin install source. "
        f"Run 'sim plugin search {name}' to discover the package, then install "
        "with a local path, direct wheel/sdist URL, git URL, or exact package "
        f"spec such as 'sim-plugin-{name}' if that package exists."
    )


def resolve_source(source: str, *, offline: bool = False,
                   index_url: str | None = None) -> ResolvedSource:
    """Classify a source argument and choose what to hand to pip.

    ``offline`` and ``index_url`` are accepted for API compatibility but no
    longer affect resolution; this resolver never reads a plugin index or maps
    short names to ``sim-plugin-*`` package names.
    """
    s = source.strip()
    _ = (offline, index_url)

    # Local files / dirs first (cheapest to check).
    p = Path(s)
    if s.startswith(("./", "../", "/", "~")) or p.exists():
        target = p.expanduser().resolve()
        if target.is_file():
            if target.suffix == ".whl":
                return ResolvedSource(kind="local-wheel", raw=s, pip_target=str(target))
            if target.name.endswith(".tar.gz") or target.suffix == ".tar":
                return ResolvedSource(kind="local-sdist", raw=s, pip_target=str(target))
            return ResolvedSource(kind="local-file", raw=s, pip_target=str(target))
        if target.is_dir():
            return ResolvedSource(kind="local-dir", raw=s, pip_target=str(target))
        # Path doesn't exist on disk and doesn't look obviously remote — error.
        if s.startswith(("./", "../", "/", "~")):
            raise FileNotFoundError(f"local path does not exist: {s}")

    # URLs — direct wheel/sdist or git.
    if s.startswith("git+"):
        return ResolvedSource(kind="git-url", raw=s, pip_target=s)
    if s.startswith(("http://", "https://")):
        if s.endswith(".whl"):
            return ResolvedSource(kind="wheel-url", raw=s, pip_target=s)
        if s.endswith(".tar.gz") or s.endswith(".tar.bz2"):
            return ResolvedSource(kind="sdist-url", raw=s, pip_target=s)
        # Generic URL: treat as wheel-url and let pip complain.
        return ResolvedSource(kind="wheel-url", raw=s, pip_target=s)

    package_match = _SIM_PLUGIN_PACKAGE_RE.match(s)
    if package_match:
        version_match = _VERSION_PIN_RE.search(s)
        version = version_match.group(1).strip() if version_match else None
        return ResolvedSource(
            kind="package-spec",
            raw=s,
            name=package_match.group(1),
            version=version,
            pip_target=s,
        )

    if _SHORT_NAME_RE.match(s):
        raise ValueError(_short_name_error(s))

    raise ValueError(f"could not classify install source: {source!r}")


# ── pip invocation ──────────────────────────────────────────────────────────


def _pip_install(target: str, *, editable: bool = False, upgrade: bool = False,
                 extra_args: list[str] | None = None,
                 python: str | None = None) -> subprocess.CompletedProcess:
    """Run ``pip install`` (or ``uv pip install`` if uv is on PATH).

    ``python`` lets the caller pin which interpreter receives the install.
    Defaults to ``sys.executable`` (the interpreter running ``sim``), which
    is the right choice in 90% of cases. The canary verification proved
    that without an explicit pin, ``uv pip install`` resolves the active
    venv via ``$VIRTUAL_ENV`` / ``$CONDA_PREFIX`` / cwd discovery, which
    can target the *wrong* interpreter when the user's terminal has no
    venv activated.
    """
    use_uv = shutil.which("uv") is not None

    target_python = python or sys.executable

    cmd: list[str]
    if use_uv:
        cmd = ["uv", "pip", "install", "--python", target_python]
    else:
        cmd = [target_python, "-m", "pip", "install"]

    if upgrade:
        cmd.append("--upgrade")
    if editable:
        cmd.append("-e")
    if extra_args:
        cmd.extend(extra_args)
    cmd.append(target)

    return subprocess.run(cmd, capture_output=True, text=True)


# ── Top-level install ──────────────────────────────────────────────────────


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
            "pip_stdout": self.pip_stdout[-2000:],   # cap for sanity
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
    """High-level installer used by ``sim plugin install``.

    Returns an InstallReport — never raises for normal failures (bad source,
    pip non-zero, sync failure). Catches and reports cleanly so the CLI
    layer can render either JSON or human output without try/except.

    ``python`` overrides the install-target interpreter. Defaults to
    ``sys.executable`` (the interpreter running ``sim``).
    """
    try:
        resolved = resolve_source(source, offline=offline)
    except (ValueError, FileNotFoundError) as e:
        return InstallReport(
            ok=False, name=None, source_kind="invalid", pip_target=source,
            pip_returncode=-1, pip_stdout="", pip_stderr="",
            error_code="PLUGIN_NOT_FOUND",
            message=str(e),
        )

    extra_args: list[str] = []
    for extra_index_url in extra_index_urls or []:
        extra_args.extend(["--extra-index-url", extra_index_url])

    proc = _pip_install(
        resolved.pip_target,
        editable=editable,
        upgrade=upgrade,
        python=python,
        extra_args=extra_args or None,
    )
    ok = proc.returncode == 0

    if not ok:
        return InstallReport(
            ok=False, name=resolved.name, source_kind=resolved.kind,
            pip_target=resolved.pip_target,
            pip_returncode=proc.returncode,
            pip_stdout=proc.stdout, pip_stderr=proc.stderr,
            error_code="PLUGIN_INSTALL_FAILED",
            message=f"pip install returned {proc.returncode}",
        )

    sync_result: dict[str, Any] | None = None
    if not skip_sync:
        try:
            from sim.plugins import sync_skills_to
            target = sync_target or _default_skills_target()
            sync_result = sync_skills_to(target)
        except Exception as e:  # noqa: BLE001 — sync is best-effort
            sync_result = {"ok": False, "message": f"{type(e).__name__}: {e}"}

    return InstallReport(
        ok=True, name=resolved.name, source_kind=resolved.kind,
        pip_target=resolved.pip_target,
        pip_returncode=proc.returncode,
        pip_stdout=proc.stdout, pip_stderr=proc.stderr,
        sync_skills=sync_result,
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


# ── Uninstall ───────────────────────────────────────────────────────────────


def uninstall_plugin(name: str, *, sync: bool = True,
                      python: str | None = None) -> dict[str, Any]:
    """Best-effort plugin uninstall.

    Tries the canonical PyPI distribution name (``sim-plugin-<name>``)
    first, then falls back to whatever package the registry says owns
    that driver. ``python`` pins the target interpreter (defaults to
    ``sys.executable``).
    """
    from sim.plugins import list_installed_plugins

    rows = {p.name: p for p in list_installed_plugins()}
    if name not in rows:
        return {"ok": False, "error_code": "PLUGIN_NOT_FOUND",
                "message": f"unknown plugin: {name!r}"}
    if rows[name].builtin:
        return {"ok": False, "error_code": "PLUGIN_INSTALL_FAILED",
                "message": "cannot uninstall a built-in driver — wait for v1.0 cut "
                           "or remove from sim-cli's _BUILTIN_REGISTRY."}

    package = rows[name].package or f"sim-plugin-{name}"
    target_python = python or sys.executable
    use_uv = shutil.which("uv") is not None
    cmd = (["uv", "pip", "uninstall", "--python", target_python, package] if use_uv
           else [target_python, "-m", "pip", "uninstall", "-y", package])
    proc = subprocess.run(cmd, capture_output=True, text=True)

    if proc.returncode != 0:
        return {"ok": False, "error_code": "PLUGIN_INSTALL_FAILED",
                "message": f"pip uninstall returned {proc.returncode}",
                "pip_stderr": proc.stderr[-1000:]}

    # Remove the on-disk skill copy if present.
    if sync:
        target = _default_skills_target() / name
        if target.is_symlink():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)
    return {"ok": True, "package": package, "name": name}


# ── Bundle ──────────────────────────────────────────────────────────────────


def bundle_plugins(names: list[str], output_dir: Path, *,
                    index_url: str | None = None) -> dict[str, Any]:
    """The install-resolver-backed bundle flow was removed.

    Use the discovery catalogue to find plugins, then download explicit wheel
    URLs or install exact package specs. The catalogue itself is not an
    install-time resolver.
    """
    _ = (names, output_dir, index_url)
    return {
        "ok": False,
        "output": str(output_dir),
        "fetched": [],
        "errors": [
            {
                "name": name,
                "error": (
                    "bundle no longer resolves catalogue names; use "
                    "sim plugin catalog/search to discover plugins, then pass "
                    "explicit wheel URLs, local artifacts, git URLs, or exact "
                    "package specs"
                ),
            }
            for name in names
        ],
    }


__all__ = [
    "ResolvedSource",
    "InstallReport",
    "resolve_source",
    "install_plugin",
    "uninstall_plugin",
    "bundle_plugins",
]
