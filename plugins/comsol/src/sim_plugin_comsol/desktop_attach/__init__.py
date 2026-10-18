"""Attach to a user-owned COMSOL Desktop through Java Shell.

This package is intentionally separate from :class:`ComsolDriver`.
It provides a small Desktop-control primitive for the copilot workflow
where the user already has COMSOL Desktop open and wants an agent to
submit Java API commands into that same visible session.
"""
from __future__ import annotations

from .health import health
from .open import open_desktop
from .shell import find_java_shell, find_java_shell_in_snapshot
from .submit import submit_code
from .target import DesktopSelector, DesktopTarget, find_desktops, resolve_target

__all__ = [
    "DesktopSelector",
    "DesktopTarget",
    "find_desktops",
    "find_java_shell",
    "find_java_shell_in_snapshot",
    "health",
    "open_desktop",
    "resolve_target",
    "submit_code",
]
