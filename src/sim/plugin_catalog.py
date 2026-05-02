"""Plugin catalogue/discovery helpers.

The catalogue answers "what plugins exist?" for users and agents. It is
intentionally separate from ``sim plugin install`` source resolution: catalogue
entries advertise an explicit install string, but installing still requires the
caller to pass that string (or any other pip-native source) to
``sim plugin install``. The catalogue is advisory metadata, not a trust
boundary or a runtime resolver.

Schema (sim-plugin-index ``index.json``, ``schema_version: 2``):

    {
      "id":           "ltspice",                  # short slug
      "name":         "LTspice",                  # display name
      "distribution": "pypi" | "wheel" | "git",   # advisory tag
      "install":      "sim-plugin-ltspice==0.2.3" # literal arg to `sim plugin install`
                      | "https://.../foo.whl#sha256=..."
                      | "git+https://...",
      "version":      "0.2.3",
      "summary":      "...",                      # optional, display only
      "homepage":     "...",                      # optional, display only
      "license_class": "oss" | "commercial"       # optional, display only
    }

The reader also accepts the legacy ``schema_version: 1`` shape (``name`` as
slug, ``latest_version``, ``latest_wheel_url``/``git``/``package``) so the
catalogue can migrate independently of sim-cli releases.
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
    """One available plugin as advertised by the discovery catalogue."""

    id: str                     # short slug, e.g. "ltspice"
    name: str = ""              # display name, e.g. "LTspice"
    distribution: str = ""      # "pypi" | "wheel" | "git" | ""
    install: str = ""           # literal arg to `sim plugin install`
    version: str = ""           # advertised current version
    summary: str = ""
    homepage: str = ""
    license_class: str = ""
    source: str = "catalog"

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "name": self.name,
            "distribution": self.distribution,
            "install": self.install,
            "version": self.version,
            "summary": self.summary,
            "homepage": self.homepage,
            "license_class": self.license_class,
            "source": self.source,
        }


def fetch_catalog(
    url: str = DEFAULT_CATALOG_URL,
    *,
    force: bool = False,
    offline: bool = False,
) -> dict[str, Any]:
    """Fetch the plugin discovery catalogue with a small local cache.

    The cache is only for discovery. It is never consulted at install time.
    """

    cache = _catalog_cache_path()
    if offline:
        if cache.is_file():
            try:
                return json.loads(cache.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {"schema_version": 2, "plugins": []}
        return {"schema_version": 2, "plugins": []}

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
        return {"schema_version": 2, "plugins": []}

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(data, encoding="utf-8")
    return parsed


def _legacy_install_string(raw: dict[str, Any]) -> tuple[str, str]:
    """Derive (install, distribution) from a v1 catalogue entry.

    v1 entries had ``package`` / ``latest_version`` / ``latest_wheel_url`` /
    ``git`` instead of a single ``install`` string. Order of preference:
    pinned wheel URL → PyPI package spec → git URL → bare package name.
    """
    package = str(raw.get("package") or raw.get("pypi_package") or "").strip()
    version = str(raw.get("latest_version") or raw.get("version") or "").strip()
    wheel_url = str(raw.get("latest_wheel_url") or "").strip()
    git_url = str(raw.get("git") or "").strip()

    if wheel_url:
        return wheel_url, "wheel"
    if package and version:
        return f"{package}=={version}", "pypi"
    if package:
        return package, "pypi"
    if git_url:
        return f"git+{git_url}", "git"
    return "", ""


def _entry_from_mapping(raw: dict[str, Any], *, source: str) -> CatalogEntry | None:
    # Slug: prefer v2 `id`, fall back to v1 `name`.
    slug = str(raw.get("id") or raw.get("name") or "").strip()
    if not slug:
        return None

    # Display name: prefer explicit `name`, fall back to slug.
    display = str(raw.get("name") or slug).strip()
    # If both `id` and `name` were absent we used `name` as slug — re-derive
    # display from the slug to avoid showing the raw key as both fields.
    if not raw.get("id") and raw.get("name"):
        display = str(raw["name"]).strip()

    distribution = str(raw.get("distribution") or "").strip()
    install = str(raw.get("install") or "").strip()
    version = str(raw.get("version") or raw.get("latest_version") or "").strip()

    # v1 fallback: synthesize install + distribution from legacy fields.
    if not install:
        install, legacy_dist = _legacy_install_string(raw)
        if not distribution:
            distribution = legacy_dist

    return CatalogEntry(
        id=slug,
        name=display,
        distribution=distribution,
        install=install,
        version=version,
        summary=str(raw.get("summary") or raw.get("description") or ""),
        homepage=str(raw.get("homepage") or raw.get("url") or raw.get("git") or ""),
        license_class=str(raw.get("license_class") or raw.get("license") or ""),
        source=source,
    )


def normalize_catalog(raw: dict[str, Any], *, source: str = "catalog") -> list[CatalogEntry]:
    """Normalize current and legacy catalogue shapes into ``CatalogEntry`` rows."""

    plugins = raw.get("plugins", [])
    if isinstance(plugins, dict):
        iterable = []
        for slug, info in plugins.items():
            if isinstance(info, dict):
                # If the value already carries `id` we trust it; otherwise
                # promote the dict key to the slug.
                item = {"id": slug, **info} if "id" not in info else dict(info)
            else:
                item = {"id": slug}
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
    return sorted(rows, key=lambda r: r.id.lower())


def list_catalog(
    *,
    query: str | None = None,
    url: str = DEFAULT_CATALOG_URL,
    offline: bool = False,
    force: bool = False,
) -> list[CatalogEntry]:
    """List available plugins from the discovery catalogue.

    ``query`` is an optional case-insensitive substring filter over
    ``id``/``name``/``summary``/``homepage``. Kept as a helper-level option for
    callers that want to filter the same data; the CLI exposes only the full
    listing (``sim plugin catalog``).
    """

    raw = fetch_catalog(url=url, offline=offline, force=force)
    rows = normalize_catalog(raw, source=url)
    if not query:
        return rows
    q = query.lower()
    return [
        row for row in rows
        if q in row.id.lower()
        or q in row.name.lower()
        or q in row.summary.lower()
        or q in row.homepage.lower()
    ]
