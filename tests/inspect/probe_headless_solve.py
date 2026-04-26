"""Verify the headless solve chain (`translator.exe` + `solexe.exe`).

Re-solves the latest `HBM_XSD_validation.<hash>` workspace under FLOUSERDIR
without going through floserv or the Flotherm GUI. This is the GUI-free
postprocessing path called out in
[svd-ai-lab/sim-proj#48](https://github.com/svd-ai-lab/sim-proj/issues/48):
once it works, the dock-readback gap (sim-skills#22) becomes optional —
GUI is only needed as an interactive 3D viewer.

Verified 2026-04-26 on Flotherm 2504:
- translator.exe exit 0 in 1.6s
- solexe.exe exit 3 (= "status 3 normal exit"; see playbook) in 23.2s
- msp_0/end/Temperature mtime advances; size + T_max round-trip via lib.msp_field

Run::

    cd <sim-cli>
    uv run python tests/inspect/probe_headless_solve.py

Output trace lands in `tests/inspect/_run_outputs/headless_solve_probe.json`.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from sim.drivers.flotherm._helpers import default_flouser, find_installation
from sim.drivers.flotherm.lib.msp_field import read_msp_field

HERE = Path(__file__).resolve().parent
RESULTS_DIR = HERE / "_run_outputs"
RESULTS_DIR.mkdir(exist_ok=True)

PROJECT_NAME = "HBM_XSD_validation"   # any solved workspace works
TRANSLATOR_TIMEOUT_S = 300
SOLEXE_TIMEOUT_S = 1200


def newest_workspace(flouser: Path, name: str) -> Path | None:
    matches = sorted(
        flouser.glob(f"{name}.*"),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    return matches[0] if matches else None


def cmd_with_env(flotherm_bat: Path, *args: str) -> str:
    """Source flotherm.bat -env then run the given exe + args.

    flotherm.bat -env exports ~30 environment variables that translator and
    solexe depend on (PATH, FLO_ROOT, schema dirs, license server, ...).
    Replicating them by hand is fragile; let the vendor wrapper do it.
    """
    quoted = " ".join(f'"{a}"' for a in args)
    return f'call "{flotherm_bat}" -env && {quoted}'


def main() -> int:
    info = find_installation()
    if info is None:
        print("ABORT — Flotherm not installed", flush=True)
        return 2

    install_root = Path(info["install_root"])
    flotherm_bat = Path(info["bat_path"])
    flouser = Path(default_flouser(str(install_root)))
    bin_dir = flotherm_bat.parent
    translator = bin_dir / "translator.exe"
    solexe = bin_dir / "solexe.exe"
    for p in (translator, solexe):
        if not p.is_file():
            print(f"ABORT — {p} not found", flush=True)
            return 2

    ws = newest_workspace(flouser, PROJECT_NAME)
    if ws is None:
        print(f"ABORT — no workspace matching {PROJECT_NAME}.* in {flouser}",
              flush=True)
        return 3

    print(f"[setup] flotherm version: {info['version']}", flush=True)
    print(f"[setup] workspace: {ws.name}", flush=True)
    print(f"[setup] translator: {translator}", flush=True)
    print(f"[setup] solexe:     {solexe}", flush=True)

    field_path = ws / "DataSets" / "BaseSolution" / "msp_0" / "end" / "Temperature"
    if not field_path.is_file():
        print(f"ABORT — Temperature not at {field_path}", flush=True)
        return 4

    pre_mtime = field_path.stat().st_mtime
    pre_size = field_path.stat().st_size
    pre_arr = read_msp_field(ws, "Temperature")
    print(f"[pre]  mtime={time.strftime('%H:%M:%S', time.localtime(pre_mtime))} "
          f"size={pre_size}B T_max={pre_arr.max():.4f} T_mean={pre_arr.mean():.4f}",
          flush=True)

    out: dict = {"flotherm_version": info["version"], "workspace": ws.name,
                 "stages": []}

    # --- translator -------------------------------------------------------
    print("\n[translator] running...", flush=True)
    t0 = time.time()
    proc = subprocess.run(
        cmd_with_env(flotherm_bat, str(translator), "-p", str(ws), "-n1"),
        shell=True, capture_output=True, timeout=TRANSLATOR_TIMEOUT_S,
    )
    trans_wall = round(time.time() - t0, 1)
    stdout = proc.stdout.decode("utf-8", errors="replace")
    stderr = proc.stderr.decode("utf-8", errors="replace")
    print(f"[translator] exit={proc.returncode} wall={trans_wall}s", flush=True)
    if stdout.strip():
        for ln in stdout.splitlines()[-10:]:
            print(f"  | {ln}", flush=True)
    out["stages"].append({"name": "translator", "exit": int(proc.returncode),
                          "wall_sec": trans_wall,
                          "stdout_tail": stdout.splitlines()[-10:],
                          "stderr_tail": stderr.splitlines()[-5:]})

    if proc.returncode != 0:
        print("[translator] FAILED — skipping solve", flush=True)
        out["verdict"] = "FAIL_TRANSLATOR"
        (RESULTS_DIR / "headless_solve_probe.json").write_text(
            json.dumps(out, indent=2, default=str)
        )
        return 5

    # --- solexe -----------------------------------------------------------
    # solexe exits with the model's "status N" code. status 3 = "normal exit
    # from main program MAINUU" per playbook. Treat 3 as the success code.
    print("\n[solexe] running...", flush=True)
    t0 = time.time()
    proc = subprocess.run(
        cmd_with_env(flotherm_bat, str(solexe), "-p", str(ws)),
        shell=True, capture_output=True, timeout=SOLEXE_TIMEOUT_S,
    )
    solve_wall = round(time.time() - t0, 1)
    stdout = proc.stdout.decode("utf-8", errors="replace")
    stderr = proc.stderr.decode("utf-8", errors="replace")
    print(f"[solexe] exit={proc.returncode} wall={solve_wall}s", flush=True)
    if stdout.strip():
        for ln in stdout.splitlines()[-15:]:
            print(f"  | {ln}", flush=True)
    out["stages"].append({"name": "solexe", "exit": int(proc.returncode),
                          "wall_sec": solve_wall,
                          "stdout_tail": stdout.splitlines()[-15:],
                          "stderr_tail": stderr.splitlines()[-5:]})

    solver_normal_exit = proc.returncode == 3

    # --- verify post-solve --------------------------------------------------
    post_mtime = field_path.stat().st_mtime
    post_size = field_path.stat().st_size
    post_arr = read_msp_field(ws, "Temperature")
    mtime_advanced = post_mtime > pre_mtime
    size_unchanged = post_size == pre_size
    stats_match = bool(
        abs(post_arr.max() - pre_arr.max()) < 0.01
        and abs(post_arr.mean() - pre_arr.mean()) < 0.05
    )
    print(f"\n[post] mtime={time.strftime('%H:%M:%S', time.localtime(post_mtime))} "
          f"size={post_size}B T_max={post_arr.max():.4f} T_mean={post_arr.mean():.4f} "
          f"advanced={mtime_advanced} stats_match={stats_match}", flush=True)

    out["pre"] = {"mtime": pre_mtime, "size": pre_size,
                  "T_max": float(pre_arr.max()), "T_mean": float(pre_arr.mean())}
    out["post"] = {"mtime": post_mtime, "size": post_size,
                   "T_max": float(post_arr.max()), "T_mean": float(post_arr.mean())}
    out["mtime_advanced"] = bool(mtime_advanced)
    out["size_unchanged"] = bool(size_unchanged)
    out["stats_match"] = stats_match
    out["solver_status_3"] = solver_normal_exit

    verdict_pass = (solver_normal_exit and mtime_advanced
                    and size_unchanged and stats_match)
    out["verdict"] = "PASS" if verdict_pass else "FAIL"

    (RESULTS_DIR / "headless_solve_probe.json").write_text(
        json.dumps(out, indent=2, default=str)
    )
    print(f"\n[trace] {RESULTS_DIR / 'headless_solve_probe.json'}", flush=True)
    print(f"[verdict] {out['verdict']}", flush=True)

    return 0 if verdict_pass else 6


if __name__ == "__main__":
    sys.exit(main())
