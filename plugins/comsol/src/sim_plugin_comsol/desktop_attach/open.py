"""Open ordinary COMSOL Desktop and prepare Java Shell attach."""
from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .shell import find_java_shell
from .target import DesktopSelector, DesktopTarget, TargetResolutionError, resolve_target


class OpenDesktopError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict:
        return {"ok": False, "status": self.code, "error": self.message, **self.details}


@dataclass(frozen=True)
class OpenResult:
    target: DesktopTarget
    reused_existing: bool
    launched_pid: int | None
    java_shell_ready: bool
    channel: dict | None = None

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "status": "ready" if self.java_shell_ready else "desktop_open",
            "reused_existing": self.reused_existing,
            "launched_pid": self.launched_pid,
            "target": self.target.to_dict(),
            "channel": self.channel,
        }


def _comsol_exe(comsol_root: str | None = None) -> Path:
    if comsol_root:
        root = Path(comsol_root)
    else:
        from sim_plugin_comsol.driver import _scan_comsol_installs

        installs = _scan_comsol_installs()
        if not installs:
            raise OpenDesktopError(
                "comsol_not_found",
                "No COMSOL installation was detected. Set COMSOL_ROOT or install COMSOL.",
            )
        root = Path(installs[0].path)
    if os.name == "nt":
        exe = root / "bin" / "win64" / "comsol.exe"
    else:
        exe = root / "bin" / "comsol"
    if not exe.is_file():
        raise OpenDesktopError("comsol_not_found", f"COMSOL launcher not found at {exe}")
    return exe


def _launch_desktop(comsol_root: str | None = None, model_file: str | None = None) -> subprocess.Popen:
    exe = _comsol_exe(comsol_root)
    args = [str(exe)]
    if model_file:
        args.append(str(Path(model_file)))
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _click_best_effort(labels: tuple[str, ...], timeout_s: float = 12) -> dict:
    if os.name != "nt":
        return {"clicked": False, "error": "UIA click requires Windows"}
    try:
        from pywinauto import Desktop
    except Exception as exc:  # noqa: BLE001
        return {"clicked": False, "error": f"pywinauto import failed: {exc}"}
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        for window in Desktop(backend="uia").windows():
            try:
                for control in window.descendants():
                    name = control.window_text() or ""
                    if name not in labels:
                        continue
                    control.click_input()
                    return {"clicked": True, "label": name, "window": window.window_text() or ""}
            except Exception:
                continue
        time.sleep(0.5)
    return {"clicked": False, "error": f"none of {labels!r} found"}


def _prepare_blank_model_if_needed(timeout_s: float = 20) -> dict:
    """Best-effort pass through Model Wizard / Blank Model startup screens."""

    # English and Chinese labels we have seen or expect from COMSOL startup.
    blank = _click_best_effort(("Blank Model", "空白模型"), timeout_s=timeout_s)
    if not blank.get("clicked"):
        return {"blank_model": blank, "done": False}
    time.sleep(1)
    done = _click_best_effort(("Done", "完成"), timeout_s=8)
    return {"blank_model": blank, "done": done}


def _open_java_shell_button(timeout_s: float = 8) -> dict:
    # The Developer ribbon exposes this as a BarToggleButton in COMSOL 6.4.
    return _click_best_effort(("Java Shell",), timeout_s=timeout_s)


def open_desktop(
    *,
    comsol_root: str | None = None,
    model_file: str | None = None,
    selector: DesktopSelector | None = None,
    timeout_s: float = 90,
    create_blank_model: bool = True,
    open_java_shell: bool = True,
) -> OpenResult:
    """Open ordinary COMSOL Desktop and return an attach-ready target."""

    selector = selector or DesktopSelector()
    try:
        target = resolve_target(selector)
        reused_existing = True
        launched_pid = None
    except TargetResolutionError:
        proc = _launch_desktop(comsol_root=comsol_root, model_file=model_file)
        reused_existing = False
        launched_pid = proc.pid
        deadline = time.time() + timeout_s
        last_error: TargetResolutionError | None = None
        target = None
        while time.time() < deadline:
            try:
                target = resolve_target(selector)
                break
            except TargetResolutionError as exc:
                last_error = exc
                time.sleep(1)
        if target is None:
            raise OpenDesktopError(
                "desktop_timeout",
                f"COMSOL Desktop did not become visible within {timeout_s}s.",
                {"last_error": last_error.to_dict() if last_error else None, "launched_pid": launched_pid},
            )

    wizard = _prepare_blank_model_if_needed() if create_blank_model and not model_file else None
    shell_button = _open_java_shell_button() if open_java_shell else None
    try:
        channel = find_java_shell(target)
        return OpenResult(
            target=target,
            reused_existing=reused_existing,
            launched_pid=launched_pid,
            java_shell_ready=True,
            channel={
                **channel.to_dict(),
                "wizard": wizard,
                "open_java_shell_button": shell_button,
            },
        )
    except Exception as exc:  # noqa: BLE001
        return OpenResult(
            target=target,
            reused_existing=reused_existing,
            launched_pid=launched_pid,
            java_shell_ready=False,
            channel={
                "error": str(exc),
                "wizard": wizard,
                "open_java_shell_button": shell_button,
            },
        )
