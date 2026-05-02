"""COMSOL Desktop target discovery and disambiguation."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Callable, Iterable


class TargetResolutionError(RuntimeError):
    """Raised when a Desktop target cannot be resolved unambiguously."""

    def __init__(self, code: str, message: str, candidates: list[dict] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.candidates = candidates or []

    def to_dict(self) -> dict:
        return {
            "ok": False,
            "status": self.code,
            "error": self.message,
            "candidates": self.candidates,
        }


@dataclass(frozen=True)
class DesktopSelector:
    """Selector for a user-owned COMSOL Desktop window."""

    desktop_pid: int | None = None
    hwnd: int | None = None
    window_title: str | None = None
    exclude_pids: frozenset[int] = field(default_factory=frozenset)


@dataclass(frozen=True)
class DesktopTarget:
    """Resolved COMSOL Desktop target metadata."""

    desktop_pid: int
    hwnd: int
    window_title: str
    process_name: str
    rect: list[int] | None = None

    @property
    def target_id(self) -> str:
        raw = f"{self.desktop_pid}|{self.hwnd}|{self.window_title}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:16]

    def to_dict(self) -> dict:
        return {
            "desktop_pid": self.desktop_pid,
            "hwnd": self.hwnd,
            "window_title": self.window_title,
            "process_name": self.process_name,
            "rect": self.rect,
            "target_id": self.target_id,
            "lifecycle_owner": "external",
            "attach_kind": "desktop",
            "control_channel": "comsol.java-shell-uia",
        }


def _default_windows_provider() -> list[dict]:
    try:
        from sim.gui import _pywinauto_tools  # type: ignore
    except Exception as exc:  # noqa: BLE001 - import varies by host
        raise TargetResolutionError(
            "uia_unavailable",
            f"sim.gui UIA helpers are unavailable: {exc}",
        ) from exc

    result = _pywinauto_tools.list_windows(())
    if not result.get("ok"):
        raise TargetResolutionError(
            "uia_unavailable",
            str(result.get("error") or "failed to enumerate windows"),
        )
    return list(result.get("windows") or [])


def _looks_like_comsol_desktop(row: dict) -> bool:
    proc = str(row.get("proc") or "").lower()
    title = str(row.get("title") or "")
    lowered_title = title.lower()
    if "comsol" not in proc and "comsol" not in lowered_title:
        return False
    if "server" in lowered_title and "connect" in lowered_title:
        return False
    return True


def _target_from_row(row: dict) -> DesktopTarget:
    return DesktopTarget(
        desktop_pid=int(row.get("pid") or 0),
        hwnd=int(row.get("hwnd") or 0),
        window_title=str(row.get("title") or ""),
        process_name=str(row.get("proc") or ""),
        rect=row.get("rect"),
    )


def find_desktops(
    selector: DesktopSelector | None = None,
    *,
    windows_provider: Callable[[], Iterable[dict]] | None = None,
) -> list[DesktopTarget]:
    """Return visible COMSOL Desktop candidates matching ``selector``."""

    selector = selector or DesktopSelector()
    provider = windows_provider or _default_windows_provider
    targets: list[DesktopTarget] = []
    for row in provider():
        if not _looks_like_comsol_desktop(row):
            continue
        target = _target_from_row(row)
        if target.desktop_pid in selector.exclude_pids:
            continue
        if selector.desktop_pid is not None and target.desktop_pid != selector.desktop_pid:
            continue
        if selector.hwnd is not None and target.hwnd != selector.hwnd:
            continue
        if selector.window_title and selector.window_title not in target.window_title:
            continue
        targets.append(target)
    return targets


def resolve_target(
    selector: DesktopSelector | None = None,
    *,
    windows_provider: Callable[[], Iterable[dict]] | None = None,
) -> DesktopTarget:
    """Resolve a single user-owned COMSOL Desktop target."""

    candidates = find_desktops(selector, windows_provider=windows_provider)
    if not candidates:
        raise TargetResolutionError(
            "target_not_found",
            "No visible COMSOL Desktop window was found.",
            [],
        )
    if len(candidates) > 1:
        raise TargetResolutionError(
            "target_ambiguous",
            "Multiple COMSOL Desktop windows were found; specify desktop_pid or hwnd.",
            [c.to_dict() for c in candidates],
        )
    return candidates[0]
