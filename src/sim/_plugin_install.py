"""Install / uninstall / bundle plugins.

The `sim plugin` group's mutating commands route through here. Discovery
and validation live in :mod:`sim.plugins`; this module only handles the
install pipeline.

A `<source>` argument can be any of:

* ``<name>`` — resolve via the index (HTTPS-only; no git, no gh).
* ``<name>@<version>`` — pinned from the index.
* ``https://...whl`` / ``https://...tar.gz`` — direct wheel/sdist URL.
* ``./path/to/dir`` — local plugin source directory.
* ``./path/to/wheel.whl`` / ``./path/to/sdist.tar.gz`` — local artifact.
* ``git+https://...`` / ``git+ssh://...`` — git URL.

The resolver classifies the source with no network calls so we know up
front what kind of install we're attempting. Then a single ``pip install``
invocation does the work.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ── Index ───────────────────────────────────────────────────────────────────

DEFAULT_INDEX_URL = (
    "https://raw.githubusercontent.com/svd-ai-lab/sim-plugin-index/main/index.json"
)

# How long an index is treated as fresh, before we re-fetch.
INDEX_CACHE_TTL_SECONDS = 3600


def _index_cache_dir() -> Path:
    return Path.home() / ".sim" / "index-cache"


def _index_cache_path() -> Path:
    return _index_cache_dir() / "index.json"


def fetch_index(url: str = DEFAULT_INDEX_URL, *, force: bool = False, offline: bool = False) -> dict[str, Any]:
    """Fetch the public plugin index. Caches under ~/.sim/index-cache/.

    In ``--offline`` mode, only the local cache is consulted; an empty index
    is returned if no cache exists.
    """
    cache = _index_cache_path()
    if offline:
        if cache.is_file():
            try:
                return json.loads(cache.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {"schema_version": 1, "plugins": []}
        return {"schema_version": 1, "plugins": []}

    if not force and cache.is_file():
        try:
            age = cache.stat().st_mtime
        except OSError:
            age = 0
        import time
        if time.time() - age < INDEX_CACHE_TTL_SECONDS:
            try:
                return json.loads(cache.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass

    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = resp.read().decode("utf-8")
    except Exception:  # noqa: BLE001 — degrade if no network
        if cache.is_file():
            try:
                return json.loads(cache.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        return {"schema_version": 1, "plugins": []}

    parsed = json.loads(data)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(data, encoding="utf-8")
    return parsed


def index_entry(name: str, *, offline: bool = False, url: str = DEFAULT_INDEX_URL) -> dict[str, Any] | None:
    """Look up one plugin by name in the index."""
    idx = fetch_index(url=url, offline=offline)
    for entry in idx.get("plugins", []):
        if entry.get("name") == name:
            return entry
    return None


# ── Source resolution ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class ResolvedSource:
    """One install source classified into a canonical kind."""
    kind: str           # "name" | "wheel-url" | "sdist-url" | "git-url" | "local-wheel" | "local-sdist" | "local-dir" | "name-version"
    raw: str            # the original argument
    name: str | None = None
    version: str | None = None
    pip_target: str = ""   # what pip install gets handed
    extras: dict[str, Any] = field(default_factory=dict)


_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_NAME_VERSION_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_]*)@([A-Za-z0-9._\-+]+)$")


def resolve_source(source: str, *, offline: bool = False, index_url: str = DEFAULT_INDEX_URL) -> ResolvedSource:
    """Classify a source argument and choose what to hand to pip.

    For named (index-resolved) installs, prefers wheel-from-release URL when
    the index entry has one; falls back to git+https. Raises ``ValueError``
    if the name isn't in the index in offline mode.
    """
    s = source.strip()

    # Local files / dirs first (cheapest to check).
    p = Path(s)
    if s.startswith(("./", "../", "/", "~")) or p.exists():
        target = p.expanduser().resolve()
        if target.is_file():
            if target.suffix == ".whl":
                return ResolvedSource(kind="local-wheel", raw=s, pip_target=str(target))
            if target.name.endswith(".tar.gz") or target.suffix == ".tar":
                return ResolvedSource(kind="local-sdist", raw=s, pip_target=str(target))
            raise ValueError(f"unsupported local file extension: {target.name}")
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

    # name@version
    m = _NAME_VERSION_RE.match(s)
    if m:
        name, version = m.group(1), m.group(2)
        entry = index_entry(name, offline=offline, url=index_url)
        if entry is None and offline:
            raise ValueError(f"plugin {name!r} not in offline index")
        if entry is None:
            # Optimistic: try by-name install; pip will error if it's wrong.
            return ResolvedSource(kind="name-version", raw=s, name=name, version=version,
                                   pip_target=f"sim-plugin-{name}=={version}")
        # Prefer the same wheel as latest if it matches; else fall back to git@version.
        if entry.get("latest_version") == version and entry.get("latest_wheel_url"):
            return ResolvedSource(kind="name-version", raw=s, name=name, version=version,
                                   pip_target=str(entry["latest_wheel_url"]))
        git = entry.get("git")
        if git:
            return ResolvedSource(kind="name-version", raw=s, name=name, version=version,
                                   pip_target=f"git+{git}@v{version}")
        return ResolvedSource(kind="name-version", raw=s, name=name, version=version,
                               pip_target=f"sim-plugin-{name}=={version}")

    # bare name
    if _NAME_RE.match(s):
        entry = index_entry(s, offline=offline, url=index_url)
        if entry is None and offline:
            raise ValueError(f"plugin {s!r} not in offline index")
        if entry is None:
            # Optimistic: assume sim-plugin-<name> is published; pip will tell us.
            return ResolvedSource(kind="name", raw=s, name=s, pip_target=f"sim-plugin-{s}")
        if entry.get("latest_wheel_url"):
            return ResolvedSource(kind="name", raw=s, name=s, pip_target=str(entry["latest_wheel_url"]))
        if entry.get("git"):
            return ResolvedSource(kind="name", raw=s, name=s, pip_target=f"git+{entry['git']}")
        return ResolvedSource(kind="name", raw=s, name=s, pip_target=f"sim-plugin-{s}")

    raise ValueError(f"could not classify install source: {source!r}")


# ── pip invocation ──────────────────────────────────────────────────────────


def _pip_install(target: str, *, editable: bool = False, upgrade: bool = False,
                 extra_args: list[str] | None = None) -> subprocess.CompletedProcess:
    """Run ``pip install`` (or ``uv pip install`` if uv is on PATH)."""
    use_uv = shutil.which("uv") is not None

    cmd: list[str]
    if use_uv:
        cmd = ["uv", "pip", "install"]
    else:
        cmd = [sys.executable, "-m", "pip", "install"]

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
) -> InstallReport:
    """High-level installer used by ``sim plugin install``.

    Returns an InstallReport — never raises for normal failures (bad source,
    pip non-zero, sync failure). Catches and reports cleanly so the CLI
    layer can render either JSON or human output without try/except.
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

    proc = _pip_install(resolved.pip_target, editable=editable, upgrade=upgrade)
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


def uninstall_plugin(name: str, *, sync: bool = True) -> dict[str, Any]:
    """Best-effort plugin uninstall.

    Tries the canonical PyPI distribution name (``sim-plugin-<name>``)
    first, then falls back to whatever package the registry says owns
    that driver.
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
    use_uv = shutil.which("uv") is not None
    cmd = (["uv", "pip", "uninstall", package] if use_uv
           else [sys.executable, "-m", "pip", "uninstall", "-y", package])
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
                    index_url: str = DEFAULT_INDEX_URL) -> dict[str, Any]:
    """Download wheels for the named plugins into ``output_dir`` for offline use.

    Produces ``<output_dir>/index.json`` filtered to just the bundled plugins,
    rewritten with ``file://`` URLs so ``sim plugin install --offline
    --from-dir <output_dir>`` works.
    """
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    idx = fetch_index(url=index_url)
    by_name = {e["name"]: e for e in idx.get("plugins", [])}

    fetched: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for name in names:
        entry = by_name.get(name)
        if entry is None:
            errors.append({"name": name, "error": "not in index"})
            continue
        wheel_url = entry.get("latest_wheel_url")
        if not wheel_url:
            errors.append({"name": name, "error": "index entry has no latest_wheel_url"})
            continue
        wheel_basename = Path(wheel_url.split("?")[0]).name
        dest = output_dir / wheel_basename
        try:
            with urllib.request.urlopen(wheel_url, timeout=30) as resp, dest.open("wb") as f:
                shutil.copyfileobj(resp, f)
        except Exception as e:  # noqa: BLE001 — surface fetch errors
            errors.append({"name": name, "error": f"download failed: {e}"})
            continue

        rewritten = dict(entry)
        rewritten["latest_wheel_url"] = f"file://{dest}"
        fetched.append(rewritten)

    bundle_idx = {"schema_version": 1, "plugins": fetched}
    (output_dir / "index.json").write_text(
        json.dumps(bundle_idx, indent=2) + "\n", encoding="utf-8",
    )

    return {
        "ok": not errors,
        "output": str(output_dir),
        "fetched": [e["name"] for e in fetched],
        "errors": errors,
    }


__all__ = [
    "DEFAULT_INDEX_URL",
    "ResolvedSource",
    "InstallReport",
    "fetch_index",
    "index_entry",
    "resolve_source",
    "install_plugin",
    "uninstall_plugin",
    "bundle_plugins",
]
