"""CLI for the COMSOL Desktop attach primitive."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .health import health
from .open import OpenDesktopError, open_desktop
from .shell import find_java_shell
from .submit import SubmitError, submit_code
from .target import DesktopSelector, TargetResolutionError, resolve_target


def _selector(args: argparse.Namespace) -> DesktopSelector:
    return DesktopSelector(
        desktop_pid=args.desktop_pid,
        hwnd=args.hwnd,
        window_title=args.window_title,
    )


def _print(payload: dict) -> int:
    print(json.dumps(payload, indent=2, ensure_ascii=True))
    return 0 if payload.get("ok") else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="comsol-desktop-attach")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_target_options(p: argparse.ArgumentParser) -> None:
        p.add_argument("--desktop-pid", type=int, default=None)
        p.add_argument("--hwnd", type=int, default=None)
        p.add_argument("--window-title", default=None)
        p.add_argument("--json", action="store_true", help="Accepted for compatibility; output is always JSON.")

    add_target_options(sub.add_parser("health"))
    add_target_options(sub.add_parser("snapshot"))

    open_p = sub.add_parser("open")
    add_target_options(open_p)
    open_p.add_argument("--comsol-root", default=None)
    open_p.add_argument("--file", type=Path, default=None)
    open_p.add_argument("--timeout", type=float, default=90)
    open_p.add_argument("--no-blank-model", action="store_true")
    open_p.add_argument("--no-java-shell", action="store_true")

    exec_p = sub.add_parser("exec")
    add_target_options(exec_p)
    group = exec_p.add_mutually_exclusive_group(required=True)
    group.add_argument("--code")
    group.add_argument("--file", type=Path)
    exec_p.add_argument("--allow-arbitrary-java", action="store_true")
    exec_p.add_argument("--submit-key", default="run_button")
    exec_p.add_argument("--audit-dir", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    selector = _selector(args)
    if args.command == "health":
        return _print(health(selector))
    if args.command == "open":
        try:
            return _print(
                open_desktop(
                    comsol_root=args.comsol_root,
                    model_file=str(args.file) if args.file else None,
                    selector=selector,
                    timeout_s=args.timeout,
                    create_blank_model=not args.no_blank_model,
                    open_java_shell=not args.no_java_shell,
                ).to_dict()
            )
        except OpenDesktopError as exc:
            return _print(exc.to_dict())
        except Exception as exc:  # noqa: BLE001
            return _print({"ok": False, "status": "open_failed", "error": str(exc)})
    if args.command == "snapshot":
        try:
            target = resolve_target(selector)
            from sim.gui import _pywinauto_tools  # type: ignore
            snapshot = _pywinauto_tools.snapshot_uia_tree((), max_depth=8)
            return _print({"ok": bool(snapshot.get("ok")), "target": target.to_dict(), "snapshot": snapshot})
        except TargetResolutionError as exc:
            return _print(exc.to_dict())
        except Exception as exc:  # noqa: BLE001
            return _print({"ok": False, "status": "snapshot_failed", "error": str(exc)})
    if args.command == "exec":
        try:
            target = resolve_target(selector)
            channel = find_java_shell(target)
            code = args.code if args.code is not None else args.file.read_text(encoding="utf-8")
            return _print(
                submit_code(
                    channel,
                    code,
                    allow_arbitrary_java=args.allow_arbitrary_java,
                    submit_key=args.submit_key,
                    audit_dir=args.audit_dir,
                )
            )
        except (TargetResolutionError, SubmitError) as exc:
            return _print(exc.to_dict())
        except Exception as exc:  # noqa: BLE001
            return _print({"ok": False, "status": "exec_failed", "error": str(exc)})
    return _print({"ok": False, "status": "unknown_command", "error": args.command})


if __name__ == "__main__":
    raise SystemExit(main())
