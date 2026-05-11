"""Locate a COMSOL documentation root on the current host.

Priority:
  1. --comsol-root / --doc-root flag (caller's responsibility to pass)
  2. COMSOL_DOC_ROOT env var (points directly at the `doc/` dir)
  3. COMSOL_ROOT env var (points at the Multiphysics install dir)
  4. sim-cli check JSON output (reuses sim-cli's install discovery)
  5. Typical per-OS install paths

The returned path is always the `doc/help/wtpwebapps/ROOT/doc/` dir that
contains the `com.comsol.help.*` Eclipse-help plugin folders.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
from pathlib import Path


DOC_SUBPATH = Path("doc") / "help" / "wtpwebapps" / "ROOT" / "doc"


def _as_doc_root(install_root: Path) -> Path | None:
    """Given a Multiphysics install dir, return its plugin-tree root if valid."""
    candidate = install_root / DOC_SUBPATH
    if candidate.is_dir() and any(candidate.glob("com.comsol.help.*")):
        return candidate
    return None


def _from_env() -> Path | None:
    doc = os.environ.get("COMSOL_DOC_ROOT")
    if doc:
        p = Path(doc)
        if p.is_dir() and any(p.glob("com.comsol.help.*")):
            return p

    root = os.environ.get("COMSOL_ROOT")
    if root:
        hit = _as_doc_root(Path(root))
        if hit:
            return hit
    return None


def _from_sim_check() -> Path | None:
    """Shell out to sim-cli check JSON output and take the first install."""
    for binary in ("sim", "ion"):
        try:
            proc = subprocess.run(
                [binary, "--json", "check", "comsol"],
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
        Path(r"C:\Program Files\COMSOL"),
        Path(r"C:\Program Files (x86)\COMSOL"),
        Path(r"D:\Program Files\COMSOL"),
    ]


def _typical_linux_bases() -> list[Path]:
    out: list[Path] = []
    for base in (Path("/usr/local"), Path("/opt"), Path("/usr/lib")):
        if not base.is_dir():
            continue
        for child in base.iterdir():
            if "comsol" in child.name.lower():
                out.append(child)
    return out


def _typical_macos_bases() -> list[Path]:
    apps = Path("/Applications")
    if not apps.is_dir():
        return []
    return [p for p in apps.iterdir() if p.name.startswith("COMSOL")]


def _from_typical_paths() -> Path | None:
    system = platform.system()
    if system == "Windows":
        for base in _typical_windows_bases():
            if not base.is_dir():
                continue
            for child in base.iterdir():
                mp = child / "Multiphysics"
                hit = _as_doc_root(mp if mp.is_dir() else child)
                if hit:
                    return hit
    elif system == "Linux":
        for child in _typical_linux_bases():
            mp = child / "multiphysics"
            hit = _as_doc_root(mp if mp.is_dir() else child)
            if hit:
                return hit
    elif system == "Darwin":
        for child in _typical_macos_bases():
            mp = child / "Multiphysics"
            hit = _as_doc_root(mp if mp.is_dir() else child)
            if hit:
                return hit
    return None


def locate_doc_root(explicit: Path | None = None) -> Path:
    """Return the plugin-tree root or raise FileNotFoundError."""
    if explicit is not None:
        hit = _as_doc_root(explicit) or (
            explicit if explicit.is_dir() and any(explicit.glob("com.comsol.help.*")) else None
        )
        if hit:
            return hit
        raise FileNotFoundError(f"No COMSOL help plugins under {explicit}")

    for finder in (_from_env, _from_sim_check, _from_typical_paths):
        hit = finder()
        if hit:
            return hit

    raise FileNotFoundError(
        "Could not locate COMSOL documentation. Set COMSOL_DOC_ROOT or COMSOL_ROOT, "
        "install sim-cli so its check command can find the install, or pass --comsol-root."
    )
