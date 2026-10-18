"""Locate a COMSOL documentation root on the current host.

Priority:
  1. --comsol-root / --doc-root flag (caller's responsibility to pass)
  2. COMSOL_DOC_ROOT env var (points directly at the `doc/` dir)
  3. COMSOL_ROOT env var (points at the Multiphysics install dir)
  4. Typical per-OS install paths and Windows Registry hints
  5. Optional sim-cli check JSON output when `sim` is installed

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
    """Optionally reuse sim-cli's install discovery when it is present."""
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


def _registry_string_value(winreg: object, key: object, name: str) -> str | None:
    try:
        value, _ = winreg.QueryValueEx(key, name)  # type: ignore[attr-defined]
    except OSError:
        return None
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _close_registry_key(key: object) -> None:
    close = getattr(key, "Close", None)
    if callable(close):
        try:
            close()
        except OSError:
            pass


def _open_registry_key(winreg: object, root: object, path: str, access: int) -> object | None:
    try:
        return winreg.OpenKey(root, path, 0, access)  # type: ignore[attr-defined]
    except OSError:
        return None


def _windows_registry_roots() -> list[Path]:
    try:
        import winreg  # type: ignore
    except ImportError:
        return []

    access_flags = [getattr(winreg, "KEY_READ", 0)]
    for view_name in ("KEY_WOW64_64KEY", "KEY_WOW64_32KEY"):
        view = getattr(winreg, view_name, 0)
        if view:
            access_flags.append(getattr(winreg, "KEY_READ", 0) | view)

    roots = [
        getattr(winreg, "HKEY_LOCAL_MACHINE", None),
        getattr(winreg, "HKEY_CURRENT_USER", None),
    ]
    uninstall_keys = [
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
    ]
    out: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        if root is None:
            continue
        for uninstall_key in uninstall_keys:
            for access in access_flags:
                parent = _open_registry_key(winreg, root, uninstall_key, access)
                if parent is None:
                    continue
                try:
                    subkey_count, _, _ = winreg.QueryInfoKey(parent)  # type: ignore[attr-defined]
                    for idx in range(subkey_count):
                        try:
                            child_name = winreg.EnumKey(parent, idx)  # type: ignore[attr-defined]
                        except OSError:
                            continue
                        child = _open_registry_key(winreg, parent, child_name, access)
                        if child is None:
                            continue
                        try:
                            display = _registry_string_value(winreg, child, "DisplayName")
                            if not display or "comsol" not in display.lower():
                                continue
                            raw = (
                                _registry_string_value(winreg, child, "InstallLocation")
                                or _registry_string_value(winreg, child, "DisplayIcon")
                                or _registry_string_value(winreg, child, "InstallSource")
                            )
                            if not raw:
                                continue
                            path_text = raw.split(",", 1)[0].strip().strip('"')
                            key = path_text.lower()
                            if key in seen:
                                continue
                            seen.add(key)
                            out.append(Path(path_text))
                        finally:
                            _close_registry_key(child)
                finally:
                    _close_registry_key(parent)

    app_paths = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
    for root in roots:
        if root is None:
            continue
        for access in access_flags:
            key = _open_registry_key(winreg, root, rf"{app_paths}\comsol.exe", access)
            if key is None:
                continue
            try:
                raw = _registry_string_value(winreg, key, "") or _registry_string_value(winreg, key, "Path")
                if raw:
                    path_text = raw.split(",", 1)[0].strip().strip('"')
                    dedupe_key = path_text.lower()
                    if dedupe_key not in seen:
                        seen.add(dedupe_key)
                        out.append(Path(path_text))
            finally:
                _close_registry_key(key)
    return out


def _from_windows_registry() -> Path | None:
    for raw in _windows_registry_roots():
        candidates = [raw, raw / "Multiphysics", raw.parent / "Multiphysics"]
        if raw.suffix.lower() == ".exe":
            candidates.extend(raw.parents)
        for candidate in candidates:
            hit = _as_doc_root(candidate)
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

    for finder in (_from_env, _from_typical_paths, _from_windows_registry, _from_sim_check):
        hit = finder()
        if hit:
            return hit

    raise FileNotFoundError(
        "Could not locate COMSOL documentation. Set COMSOL_DOC_ROOT or COMSOL_ROOT, "
        "pass --comsol-root, or provide the COMSOL install path explicitly."
    )
