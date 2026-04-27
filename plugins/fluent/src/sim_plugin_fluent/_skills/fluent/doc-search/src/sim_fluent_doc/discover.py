"""Locate an Ansys Fluent documentation root on the current host.

Priority:
  1. --ansys-root flag (caller's responsibility to pass)
  2. FLUENT_DOC_ROOT env var (points directly at the help dir)
  3. AWP_ROOT{NNN} env vars (e.g. AWP_ROOT252) — latest release wins
  4. `sim check fluent --json` (reuses sim-cli's install discovery)
  5. Typical per-OS install paths

The returned path is always the `commonfiles/help/en-us/help/` dir
that contains the `flu_*`, `pyfluent*`, and `wb2_*` topic folders.
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
from pathlib import Path


DOC_SUBPATH = Path("commonfiles") / "help" / "en-us" / "help"

# Well-known topic folders that strongly signal a valid help root.
_SIGNAL_FOLDERS = ("flu_ug", "flu_th", "pyfluent")

_AWP_ROOT_RE = re.compile(r"^AWP_ROOT(\d{3})$")


def _looks_like_help_root(candidate: Path) -> bool:
    """Return True if `candidate` appears to be a Fluent help dir."""
    if not candidate.is_dir():
        return False
    # Strong signal: one of the well-known topic folders is present.
    if any((candidate / name).is_dir() for name in _SIGNAL_FOLDERS):
        return True
    # Fallback for future/older releases: at least one child dir
    # (named flu_*, pyfluent*, or wb2_*) contains .html files.
    for child in candidate.iterdir():
        if not child.is_dir():
            continue
        name = child.name
        if not (name.startswith("flu_") or name.startswith("pyfluent") or name.startswith("wb2_")):
            continue
        try:
            next(child.rglob("*.html"))
        except StopIteration:
            continue
        return True
    return False


def _as_doc_root(install_root: Path) -> Path | None:
    """Accept either an AWP root or a help dir; return the help dir if valid."""
    if _looks_like_help_root(install_root):
        return install_root
    candidate = install_root / DOC_SUBPATH
    if _looks_like_help_root(candidate):
        return candidate
    return None


def _from_env() -> Path | None:
    doc = os.environ.get("FLUENT_DOC_ROOT")
    if doc:
        p = Path(doc)
        if _looks_like_help_root(p):
            return p

    # AWP_ROOT{NNN} — iterate all matching vars, prefer the highest suffix.
    candidates: list[tuple[int, Path]] = []
    for key, val in os.environ.items():
        m = _AWP_ROOT_RE.match(key)
        if not m or not val:
            continue
        candidates.append((int(m.group(1)), Path(val)))
    candidates.sort(reverse=True)
    for _, root in candidates:
        hit = _as_doc_root(root)
        if hit:
            return hit
    return None


def _from_sim_check() -> Path | None:
    """Shell out to `sim check fluent --json` and take the first install."""
    for binary in ("sim", "ion"):
        try:
            proc = subprocess.run(
                [binary, "--json", "check", "fluent"],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        if proc.returncode != 0:
            continue
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            continue
        installs = payload.get("data", {}).get("installs") or []
        for entry in installs:
            p = entry.get("path")
            if not p:
                continue
            hit = _as_doc_root(Path(p))
            if hit:
                return hit
    return None


def _typical_windows_bases() -> list[Path]:
    return [
        Path(r"C:\Program Files\ANSYS Inc"),
        Path(r"C:\Program Files (x86)\ANSYS Inc"),
        Path(r"D:\Program Files\ANSYS Inc"),
    ]


def _typical_linux_bases() -> list[Path]:
    return [
        Path("/usr/ansys_inc"),
        Path("/opt/ansys_inc"),
        Path("/ansys_inc"),
    ]


def _iter_version_dirs(base: Path) -> list[Path]:
    """Return child dirs of `base` whose name looks like 'v{NNN}', newest first."""
    if not base.is_dir():
        return []
    out: list[tuple[int, Path]] = []
    for child in base.iterdir():
        if not child.is_dir():
            continue
        name = child.name
        if len(name) == 4 and name[0].lower() == "v" and name[1:].isdigit():
            out.append((int(name[1:]), child))
    out.sort(reverse=True)
    return [p for _, p in out]


def _from_typical_paths() -> Path | None:
    system = platform.system()
    if system == "Windows":
        bases = _typical_windows_bases()
    elif system == "Linux":
        bases = _typical_linux_bases()
    else:
        # macOS (Darwin) and everything else: no Ansys Fluent distribution.
        return None

    for base in bases:
        for vdir in _iter_version_dirs(base):
            hit = _as_doc_root(vdir)
            if hit:
                return hit
    return None


def locate_doc_root(explicit: Path | None = None) -> Path:
    """Return the help-dir root or raise FileNotFoundError."""
    if explicit is not None:
        hit = _as_doc_root(explicit)
        if hit:
            return hit
        raise FileNotFoundError(f"No Fluent help topic folders under {explicit}")

    for finder in (_from_env, _from_sim_check, _from_typical_paths):
        hit = finder()
        if hit:
            return hit

    raise FileNotFoundError(
        "Could not locate Ansys Fluent documentation. Set FLUENT_DOC_ROOT or "
        "AWP_ROOT{NNN}, install sim-cli so `sim check fluent` can find the install, "
        "or pass --ansys-root."
    )
