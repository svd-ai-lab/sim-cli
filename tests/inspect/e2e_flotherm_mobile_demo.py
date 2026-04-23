"""Real Flotherm end-to-end simulation — Mobile_Demo_Steady_State.

Runs the full load-and-solve lifecycle against a live Flotherm 2504 GUI:
  1. launch Flotherm GUI (creates flouser workspace)
  2. import Mobile_Demo-Steady_State.pack via `driver.run(<pack>)`
     (uses project_import FloSCRIPT → pywinauto file dialog → load)
  3. trigger steady-state solver via `driver.run("solve")`
     (plays `<start start_type="solver"/>` FloSCRIPT)
  4. poll the Message Window dock (UIA subprocess) every 30s up to
     MAX_SOLVE_SEC, emit progress, stop on convergence / failure marker
  5. disconnect

Reference outcome (sim-skills/flotherm/base/workflows/solve_mobile_demo.xml
comment, verified 2026-04-02/03 + 2026-04-11 on the same workstation):
  ~153,449 grid cells, steady-state converged, "I/9001 - Solver stopped:
  steady solution converged", status 3 normal exit.

Run:
    cd E:/simcli/sim-cli
    .venv/Scripts/python.exe tests/inspect/e2e_flotherm_mobile_demo.py

Output:
    tests/inspect/_run_outputs/flotherm_mobile_demo_e2e.json
    tests/inspect/_run_outputs/flotherm_mobile_demo_dock.log
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
RESULTS_DIR = HERE / "_run_outputs"
RESULTS_DIR.mkdir(exist_ok=True)

PACK = Path(
    r"E:\simcli\sim-skills\flotherm\base\reference\flotherm\2504"
    r"\examples\pack\Mobile_Demo-Steady_State.pack"
)
MAX_SOLVE_SEC = int(600)             # 10 minutes ceiling — Mobile_Demo is tiny
POLL_INTERVAL_SEC = 15               # poll dock every 15s

# Flotherm 2504 dock convergence/failure codes. The "Solver stopped"
# message comes with either I/8003 (normal steady convergence) or
# I/9001 (same string, older build). We accept both.
CONVERGED_MARKERS = ("I/8003", "I/9001",
                     "Solver stopped: steady solution converged")
FAILED_MARKERS = ("E/", "F/")        # flotherm error codes
PROGRESS_MARKER = "I/"               # any info line is progress


def banner(s: str) -> None:
    print("\n" + "=" * 78, flush=True)
    print(f"  {s}", flush=True)
    print("=" * 78, flush=True)


def main() -> int:
    if not PACK.is_file():
        print(f"ABORT — pack not found: {PACK}")
        return 1

    from sim.drivers.flotherm.driver import FlothermDriver
    from sim.drivers.flotherm._win32_backend import read_message_dock

    driver = FlothermDriver()

    banner("Flotherm Mobile_Demo — real e2e (import + solve + poll)")
    print(f" pack       : {PACK}", flush=True)
    print(f" max solve  : {MAX_SOLVE_SEC}s", flush=True)

    t0 = time.time()
    info = driver.launch(ui_mode="gui")
    launch_sec = round(time.time() - t0, 1)
    print(f"[launch] ok in {launch_sec}s  pid={info.get('process_pid')}  "
          f"install={info.get('install_root')}", flush=True)

    # Wait until the Flotherm main window appears instead of sleeping a fixed
    # duration — faster on fast machines, robust on slow ones.
    print("[launch] waiting for Flotherm main window (up to 60s) ...", flush=True)
    _win = driver._gui.find(title_contains="Flotherm", timeout_s=60)
    if _win:
        print(f"[launch] main window: {_win.title!r}", flush=True)
    else:
        print("[launch] warning: Flotherm window not found within 60s", flush=True)

    trace: dict = {
        "pack": str(PACK),
        "launch_sec": launch_sec,
        "stages": [],
    }
    dock_log_lines: list[str] = []

    try:
        # ── Stage 1: import pack ────────────────────────────────────────────
        banner("Stage 1 — import pack")
        t0 = time.time()
        import_res = driver.run(str(PACK), label="import_pack")
        import_sec = round(time.time() - t0, 1)
        print(f"  wall         : {import_sec}s", flush=True)
        print(f"  ok           : {import_res.get('ok')}", flush=True)
        print(f"  gui.ok       : {(import_res.get('gui') or {}).get('ok')}",
              flush=True)
        print(f"  gui.method   : {(import_res.get('gui') or {}).get('method')}",
              flush=True)
        trace["stages"].append({
            "name": "import_pack", "wall_sec": import_sec,
            "ok": import_res.get("ok"),
            "gui_ok": (import_res.get("gui") or {}).get("ok"),
            "gui_errors": (import_res.get("gui") or {}).get("errors"),
        })
        if not import_res.get("ok"):
            banner("IMPORT FAILED — aborting")
            return 2

        # Poll dock until import produces output (up to 20s) instead of fixed sleep.
        _deadline = time.time() + 20
        post_import_dock: list[str] = []
        while time.time() < _deadline:
            post_import_dock = read_message_dock(timeout=5)
            if post_import_dock:
                break
            time.sleep(0.5)
        print(f"\n  post-import dock ({len(post_import_dock)} lines):",
              flush=True)
        for ln in post_import_dock[-15:]:
            print(f"    | {ln}", flush=True)
        dock_log_lines.append(f"--- post-import dock ({time.strftime('%H:%M:%S')}) ---")
        dock_log_lines.extend(post_import_dock)
        trace["stages"][-1]["post_dock_tail"] = post_import_dock[-15:]

        # ── Stage 2: trigger solve ──────────────────────────────────────────
        banner("Stage 2 — trigger steady-state solver")
        t0 = time.time()
        solve_res = driver.run("solve", label="solve_start")
        solve_trigger_sec = round(time.time() - t0, 1)
        print(f"  trigger wall : {solve_trigger_sec}s", flush=True)
        print(f"  ok           : {solve_res.get('ok')}", flush=True)
        print(f"  gui.ok       : {(solve_res.get('gui') or {}).get('ok')}",
              flush=True)
        trace["stages"].append({
            "name": "solve_start", "wall_sec": solve_trigger_sec,
            "ok": solve_res.get("ok"),
            "gui_ok": (solve_res.get("gui") or {}).get("ok"),
            "gui_errors": (solve_res.get("gui") or {}).get("errors"),
        })

        # ── Stage 3: poll dock until converged / failed / timeout ───────────
        banner(f"Stage 3 — poll dock (interval {POLL_INTERVAL_SEC}s, "
               f"max {MAX_SOLVE_SEC}s)")
        poll_start = time.time()
        converged = False
        fatal = False
        last_seen: set[str] = set(post_import_dock)
        progress: list[dict] = []

        while True:
            elapsed = round(time.time() - poll_start)
            if elapsed >= MAX_SOLVE_SEC:
                print(f"[{elapsed}s] TIMEOUT — exceeded {MAX_SOLVE_SEC}s",
                      flush=True)
                break

            time.sleep(POLL_INTERVAL_SEC)
            elapsed = round(time.time() - poll_start)
            dock = read_message_dock(timeout=20)
            new = [ln for ln in dock if ln not in last_seen]
            last_seen.update(dock)

            if not new:
                print(f"[{elapsed:4}s] (no new dock lines; "
                      f"total={len(dock)})", flush=True)
                progress.append({"elapsed_sec": elapsed,
                                 "new_lines": 0, "total_lines": len(dock)})
                continue

            dock_log_lines.append(
                f"--- poll @ {elapsed}s ({time.strftime('%H:%M:%S')}) ---"
            )
            dock_log_lines.extend(new)

            print(f"[{elapsed:4}s] +{len(new)} new dock lines:", flush=True)
            for ln in new[-8:]:
                print(f"         | {ln[:150]}", flush=True)

            converged_line = next(
                (ln for ln in new
                 if any(m in ln for m in CONVERGED_MARKERS)),
                None,
            )
            if converged_line:
                converged = True
                print(f"\n[{elapsed}s] *** CONVERGED ***", flush=True)
                print(f"           {converged_line}", flush=True)
                progress.append({"elapsed_sec": elapsed,
                                 "new_lines": len(new),
                                 "converged_line": converged_line})
                break

            fatal_line = next(
                (ln for ln in new
                 if any(m in ln for m in FAILED_MARKERS)
                 and "0 errors" not in ln.lower()),
                None,
            )
            if fatal_line:
                fatal = True
                print(f"\n[{elapsed}s] *** FATAL ***  {fatal_line}",
                      flush=True)
                progress.append({"elapsed_sec": elapsed,
                                 "new_lines": len(new),
                                 "fatal_line": fatal_line})
                break

            progress.append({"elapsed_sec": elapsed,
                             "new_lines": len(new),
                             "total_lines": len(dock)})

        total_solve_sec = round(time.time() - poll_start)
        trace["stages"].append({
            "name": "solve_poll",
            "wall_sec": total_solve_sec,
            "converged": converged,
            "fatal": fatal,
            "progress_checkpoints": progress,
        })

        # Final dock snapshot
        final_dock = read_message_dock(timeout=20)
        trace["final_dock_tail"] = final_dock[-30:]
        dock_log_lines.append(f"--- final dock ({time.strftime('%H:%M:%S')}) ---")
        dock_log_lines.extend(final_dock)

    finally:
        banner("disconnect")
        try:
            r = driver.disconnect()
            print(f"  disconnect = {r}", flush=True)
        except Exception as exc:
            print(f"  disconnect warn: {exc}", flush=True)

    # ── verdict ───────────────────────────────────────────────────────────
    converged = any(
        s.get("converged") for s in trace["stages"]
        if s.get("name") == "solve_poll"
    )
    solve_stage = next(
        (s for s in trace["stages"] if s.get("name") == "solve_poll"), {}
    )
    solve_sec = solve_stage.get("wall_sec", 0)

    banner("RESULT SUMMARY")
    print(f"  launch_sec           : {launch_sec}", flush=True)
    print(f"  import_sec           : {trace['stages'][0].get('wall_sec')}",
          flush=True)
    print(f"  solve_poll_sec       : {solve_sec}", flush=True)
    print(f"  converged            : {converged}", flush=True)
    if trace.get("final_dock_tail"):
        print(f"\n  final dock last 10 lines:", flush=True)
        for ln in trace["final_dock_tail"][-10:]:
            print(f"    | {ln[:150]}", flush=True)

    verdict = converged
    banner(f"VERDICT — Flotherm real e2e: {'PASS' if verdict else 'FAIL'}")

    out_path = RESULTS_DIR / "flotherm_mobile_demo_e2e.json"
    out_path.write_text(json.dumps(trace, indent=2, default=str))
    dock_path = RESULTS_DIR / "flotherm_mobile_demo_dock.log"
    dock_path.write_text("\n".join(dock_log_lines), encoding="utf-8")
    print(f"\n[trace] {out_path}", flush=True)
    print(f"[dock]  {dock_path}", flush=True)

    return 0 if verdict else 3


if __name__ == "__main__":
    sys.exit(main())
