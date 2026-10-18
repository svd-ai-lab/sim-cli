"""Health composition for COMSOL Desktop attach."""
from __future__ import annotations

from .shell import JavaShellError, find_java_shell
from .target import DesktopSelector, TargetResolutionError, resolve_target


def health(selector: DesktopSelector | None = None) -> dict:
    """Return target/channel/session health for a Desktop attach target."""

    try:
        target = resolve_target(selector)
    except TargetResolutionError as exc:
        return {
            **exc.to_dict(),
            "target_alive": False,
            "channel_alive": False,
            "session_alive": False,
        }
    try:
        channel = find_java_shell(target)
    except JavaShellError as exc:
        return {
            **exc.to_dict(),
            "target": target.to_dict(),
            "target_alive": True,
            "channel_alive": False,
            "session_alive": False,
        }
    return {
        "ok": True,
        "status": "ready",
        "target": target.to_dict(),
        "channel": channel.to_dict(),
        "target_alive": True,
        "channel_alive": True,
        "session_alive": True,
    }
