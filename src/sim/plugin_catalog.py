"""Plugin catalogue/discovery helpers.

The catalogue answers "what plugins exist?" for users and agents. It is
intentionally separate from ``sim plugin install`` source resolution: catalogue
entries may suggest explicit install commands, but installing still requires a
pip-native package spec, URL, git URL, or local path.
"""
from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_CATALOG_URL = (
    "https://raw.githubusercontent.com/svd-ai-lab/sim-plugin-index/main/index.json"
)
CATALOG_CACHE_TTL_SECONDS = 3600


def _catalog_cache_path() -> Path:
    return Path.home() / ".sim" / "index-cache" / "catalog.json"


@dataclass(frozen=True)
class CatalogEntry:
    """One available plugin as shown by the discovery catalogue."""

    name: str
    package: str
    summary: str = ""
    homepage: str = ""
    license_class: str = ""
    latest_version: str = ""
    install_command: str = ""
    source: str = "catalog"

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "package": self.package,
            "summary": self.summary,
            "homepage": self.homepage,
            "license_class": self.license_class,
            "latest_version": self.latest_version,
            "install_command": self.install_command,
            "source": self.source,
        }


def fetch_catalog(
    url: str = DEFAULT_CATALOG_URL,
    *,
    force: bool = False,
    offline: bool = False,
) -> dict[str, Any]:
    """Fetch the plugin discovery catalogue with a small local cache.

    The cache is only for discovery. It is never used by ``resolve_source`` or
    install-time short-name resolution.
    """

    cache = _catalog_cache_path()
    if offline:
        if cache.is_file():
            try:
                return json.loads(cache.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {"schema_version": 1, "plugins": []}
        return {"schema_version": 1, "plugins": []}

    if not force and cache.is_file():
        try:
            if time.time() - cache.stat().st_mtime < CATALOG_CACHE_TTL_SECONDS:
                return json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass

    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = resp.read().decode("utf-8")
        parsed = json.loads(data)
    except Exception:  # noqa: BLE001 - discovery should degrade gracefully
        if cache.is_file():
            try:
                return json.loads(cache.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        return {"schema_version": 1, "plugins": []}

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(data, encoding="utf-8")
    return parsed


def _default_package_name(name: str) -> str:
    return f"sim-plugin-{name.replace('_', '-')}"


def _entry_from_mapping(raw: dict[str, Any], *, source: str) -> CatalogEntry | None:
    name = str(raw.get("name") or "").strip()
    if not name:
        return None

    package = str(raw.get("package") or raw.get("pypi_package") or _default_package_name(name))
    latest_version = str(raw.get("latest_version") or raw.get("version") or "")
    install = raw.get("install")
    install_command = ""
    if isinstance(install, dict):
        install_command = str(install.get("command") or "")
    elif isinstance(install, str):
        install_command = install
    if not install_command:
        install_command = f"sim plugin install {package}"
        if latest_version and raw.get("pin_latest"):
            install_command = f"sim plugin install {package}=={latest_version}"

    return CatalogEntry(
        name=name,
        package=package,
        summary=str(raw.get("summary") or raw.get("description") or ""),
        homepage=str(raw.get("homepage") or raw.get("url") or raw.get("git") or ""),
        license_class=str(raw.get("license_class") or raw.get("license") or ""),
        latest_version=latest_version,
        install_command=install_command,
        source=source,
    )


def normalize_catalog(raw: dict[str, Any], *, source: str = "catalog") -> list[CatalogEntry]:
    """Normalize current and future catalogue shapes into ``CatalogEntry`` rows."""

    plugins = raw.get("plugins", [])
    if isinstance(plugins, dict):
        iterable = []
        for name, info in plugins.items():
            if isinstance(info, dict):
                item = {"name": name, **info}
            else:
                item = {"name": name}
            iterable.append(item)
    elif isinstance(plugins, list):
        iterable = [p for p in plugins if isinstance(p, dict)]
    else:
        iterable = []

    rows = []
    for item in iterable:
        row = _entry_from_mapping(item, source=source)
        if row is not None:
            rows.append(row)
    return sorted(rows, key=lambda r: r.name.lower())


def list_catalog(
    *,
    query: str | None = None,
    url: str = DEFAULT_CATALOG_URL,
    offline: bool = False,
    force: bool = False,
) -> list[CatalogEntry]:
    """List/search available plugins from the discovery catalogue."""

    raw = fetch_catalog(url=url, offline=offline, force=force)
    rows = normalize_catalog(raw, source=url)
    if not query:
        return rows
    q = query.lower()
    return [
        row for row in rows
        if q in row.name.lower()
        or q in row.package.lower()
        or q in row.summary.lower()
        or q in row.homepage.lower()
    ]
