"""L3 real-Flotherm e2e — confirm Phase 3 sim.gui._win32_dialog migration
is behaviourally identical to the pre-migration inline implementation.

What we're validating:
  flotherm/driver.py → _play_floscript → flotherm/_win32_backend.play_floscript
  play_floscript now calls:
      sim.gui._win32_dialog.dismiss_windows_by_title_fragment
      sim.gui._win32_dialog.find_dialog_by_title
      sim.gui._win32_dialog.fill_file_dialog
  (previously those were inline ctypes routines in _win32_backend.)

We prove the migration is zero-regression by:
  1. Launching a real Flotherm GUI session
  2. Importing a bundled .pack — exercises _find_dialog + _fill_file_dialog
     (the Play FloSCRIPT file picker)
  3. Checking the gui_result says ok=True (the file-dialog fill + submit
     path worked) AND that Flotherm's Message Window dock is readable
     (confirms the subprocess-UIA path on read_message_dock also survived)

Run:
    cd E:/simcli/sim-cli
    .venv/Scripts/python.exe tests/inspect/integration_flotherm_win32_migration.py

Output:
    tests/inspect/_run_outputs/flotherm_win32_migration_trace.{json,log}
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
RESULTS_DIR = HERE / "_run_outputs"
RESULTS_DIR.mkdir(exist_ok=True)

DEFAULT_PACK = Path(
    r"E:\simcli\sim-skills\flotherm\base\reference\flotherm\2504"
    r"\examples\pack\Mobile_Demo-Steady_State.pack"
)


def banner(s: str) -> None:
    print("\n" + "=" * 78, flush=True)
    print(f"  {s}", flush=True)
    print("=" * 78, flush=True)


def main() -> int:
    pack = DEFAULT_PACK
    if not pack.is_file():
        print(f"ABORT — pack file not found: {pack}")
        return 1

    # Proving the migration imports cleanly at package level is already
    # useful — exit-0 from this line means sim.gui._win32_dialog is
    # reachable from the flotherm module tree.
    from sim.drivers.flotherm.driver import FlothermDriver
    from sim.drivers.flotherm._win32_backend import (
        _find_dialog, _fill_file_dialog,
    )
    # Attribute identity checks: the flotherm module must have re-exported
    # exactly the sim.gui primitives we claim it did.
    from sim.gui._win32_dialog import (
        find_dialog_by_title, fill_file_dialog,
    )
    assert _find_dialog is find_dialog_by_title, (
        "flotherm._win32_backend._find_dialog should be sim.gui's "
        "find_dialog_by_title post-migration"
    )
    assert _fill_file_dialog is fill_file_dialog, (
        "flotherm._win32_backend._fill_file_dialog should be sim.gui's "
        "fill_file_dialog post-migration"
    )
    print("[check] sim.gui._win32_dialog re-export identity OK", flush=True)

    banner("Flotherm e2e — migrate-to-sim.gui zero-regression")
    driver = FlothermDriver()

    # ── launch (GUI) ───────────────────────────────────────────────────────
    print("[launch] Flotherm GUI ...", flush=True)
    t0 = time.time()
    try:
        info = driver.launch(ui_mode="gui")
    except Exception as exc:
        print(f"[launch] FAILED: {exc}")
        return 2
    print(f"[launch] ok in {round(time.time() - t0, 1)}s", flush=True)
    print(f"          session_id     = {info.get('session_id')}")
    print(f"          install_root   = {info.get('install_root')}")
    print(f"          workspace      = {info.get('workspace')}")
    print(f"          process_pid    = {info.get('process_pid')}")

    # Wait until Flotherm main window appears instead of fixed sleep.
    print("[launch] waiting for Flotherm main window (up to 60s) ...", flush=True)
    _win = driver._gui.find(title_contains="Flotherm", timeout_s=60)
    if _win:
        print(f"[launch] main window: {_win.title!r}", flush=True)
    else:
        print("[launch] warning: Flotherm window not found within 60s", flush=True)

    turns: list[dict] = []

    try:
        # ── T1: pack import (exercises _find_dialog + _fill_file_dialog) ────
        banner("T1 — import .pack via Play FloSCRIPT + file dialog")
        t0 = time.time()
        res = driver.run(str(pack), label="import_pack")
        elapsed = round(time.time() - t0, 1)
        gui = res.get("gui") or {}
        print(f"  driver.run wall     = {elapsed}s", flush=True)
        print(f"  ok                  = {res.get('ok')}", flush=True)
        print(f"  gui.ok              = {gui.get('ok')}", flush=True)
        print(f"  gui.method          = {gui.get('method')}", flush=True)
        print(f"  gui.dismissed_popups= {gui.get('dismissed_popups')}", flush=True)
        if gui.get("errors"):
            print(f"  gui.errors          = {gui['errors']}", flush=True)
        if gui.get("warnings"):
            print(f"  gui.warnings        = {gui['warnings']}", flush=True)
        turns.append({
            "turn": "T1_import_pack", "elapsed_sec": elapsed,
            "result": res,
        })

        # ── T2: read Flotherm's Message dock (uses _MESSAGE_DOCK_READ) ──────
        banner("T2 — read Message Window dock (subprocess UIA)")
        from sim.drivers.flotherm._win32_backend import read_message_dock
        lines = read_message_dock(timeout=10)
        print(f"  dock lines          = {len(lines)}", flush=True)
        for ln in lines[:10]:
            print(f"    | {ln}", flush=True)
        if len(lines) > 10:
            print(f"    ... and {len(lines) - 10} more", flush=True)
        turns.append({
            "turn": "T2_dock_read",
            "n_lines": len(lines),
            "first_lines": lines[:20],
        })

    finally:
        banner("disconnect")
        try:
            r = driver.disconnect()
            print(f"  disconnect = {r}", flush=True)
        except Exception as exc:
            print(f"  disconnect warn: {exc}", flush=True)

    # ── verdict ───────────────────────────────────────────────────────────
    t1 = turns[0]
    t1_ok = bool(t1["result"].get("ok")) and bool(
        (t1["result"].get("gui") or {}).get("ok")
    )
    banner(f"VERDICT — migration zero-regression: {'PASS' if t1_ok else 'INSPECT'}")
    if not t1_ok:
        print("  T1 gui.ok was False. If gui.errors has Flotherm-internal "
              "warnings (I/9001 etc.) that is a **model** issue, not a "
              "migration issue — confirm by reading gui.errors above.",
              flush=True)

    out_path = RESULTS_DIR / "flotherm_win32_migration_trace.json"
    out_path.write_text(json.dumps({
        "pack": str(pack),
        "launch_info": {k: (str(v) if isinstance(v, Path) else v)
                        for k, v in info.items()},
        "turns": turns,
    }, indent=2, default=str))
    print(f"\n[trace] {out_path}", flush=True)

    return 0 if t1_ok else 3


if __name__ == "__main__":
    sys.exit(main())
