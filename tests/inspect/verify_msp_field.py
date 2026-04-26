"""Verify `lib.msp_field.read_msp_field` against real solved workspaces.

Reads the latest workspace for each named project under FLOUSERDIR and
checks that mesh dims + Temperature stats match the reference values
captured 2026-04-26 on Flotherm 2504.

Run on a Windows host with Flotherm 2504 + at least one solved project::

    cd <sim-cli>
    uv run python tests/inspect/verify_msp_field.py

Output trace lands in `tests/inspect/_run_outputs/verify_msp_field.json`.

Sets exit code 0 on PASS, 1 if any case fails.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from sim.drivers.flotherm._helpers import default_flouser, find_installation
from sim.drivers.flotherm.lib.msp_field import (
    list_fields,
    read_mesh_dims,
    read_msp_field,
)

HERE = Path(__file__).resolve().parent
RESULTS_DIR = HERE / "_run_outputs"
RESULTS_DIR.mkdir(exist_ok=True)

# Reference stats captured 2026-04-26, Flotherm 2504
CASES = [
    {
        "name": "HBM_XSD_validation",
        "expected_dims": (25, 32, 25),
        "expected_n": 20000,
        "expected_T_min_approx": 25.244,
        "expected_T_max_approx": 60.039,
        "expected_T_mean_approx": 33.59,
        "tol": 0.01,
    },
    {
        "name": "Mobile_Demo_Steady_State",
        "expected_dims": (19, 17, 9),
        "expected_n": 2907,
        "expected_T_min_approx": 35.000,
        "expected_T_max_approx": 35.332,
        "expected_T_mean_approx": 35.014,
        "tol": 0.01,
    },
    {
        "name": "HBM_3block_v1b_plus",
        "expected_dims": (44, 155, 44),
        "expected_n": 300080,
        "expected_T_min_approx": 25.747,
        "expected_T_max_approx": 60.034,
        "expected_T_mean_approx": 38.253,
        "tol": 0.01,
    },
]


def newest_workspace(flouser: Path, name: str) -> Path | None:
    matches = sorted(
        flouser.glob(f"{name}.*"),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    return matches[0] if matches else None


def main() -> int:
    info = find_installation()
    if info is None:
        print("ABORT — Flotherm not installed", flush=True)
        return 2
    flouser = Path(default_flouser(info["install_root"]))
    if not flouser.is_dir():
        print(f"ABORT — FLOUSERDIR not found: {flouser}", flush=True)
        return 2

    print(f"[setup] flouser: {flouser}", flush=True)
    print(f"[setup] flotherm version: {info['version']}", flush=True)

    out: list[dict] = []
    overall_ok = True
    any_present = False

    for case in CASES:
        result: dict = {"name": case["name"]}
        ws = newest_workspace(flouser, case["name"])
        if ws is None:
            result["error"] = f"no workspace matching {case['name']}.*"
            result["ok"] = False
            out.append(result)
            print(f"[{case['name']}] MISSING — workspace not present", flush=True)
            continue
        any_present = True
        result["workspace_basename"] = ws.name

        try:
            dims = read_mesh_dims(ws)
            fields = list_fields(ws)
            arr = read_msp_field(ws, "Temperature")
        except Exception as e:
            result["error"] = f"{type(e).__name__}: {e}"
            result["ok"] = False
            overall_ok = False
            out.append(result)
            print(f"[{case['name']}] ERROR: {e}", flush=True)
            continue

        result["dims"] = list(dims)
        result["n_fields"] = len(fields)
        result["array_shape"] = list(int(s) for s in arr.shape)
        result["array_size"] = int(arr.size)
        result["T_min"] = float(arr.min())
        result["T_max"] = float(arr.max())
        result["T_mean"] = float(arr.mean())
        result["T_std"] = float(arr.std())

        ok = bool(
            dims == case["expected_dims"]
            and arr.size == case["expected_n"]
            and abs(arr.min() - case["expected_T_min_approx"]) < case["tol"]
            and abs(arr.max() - case["expected_T_max_approx"]) < case["tol"]
            and abs(arr.mean() - case["expected_T_mean_approx"]) < case["tol"]
        )
        result["ok"] = ok
        if not ok:
            overall_ok = False

        print(
            f"[{case['name']}] dims={dims} n_fields={len(fields)} "
            f"T_min={arr.min():.4f} T_max={arr.max():.4f} "
            f"T_mean={arr.mean():.4f} ok={ok}",
            flush=True,
        )
        out.append(result)

    summary = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "flotherm_version": info["version"],
        "flouser": str(flouser),
        "all_present_cases_ok": overall_ok,
        "cases": out,
    }
    out_path = RESULTS_DIR / "verify_msp_field.json"
    out_path.write_text(json.dumps(summary, indent=2))
    print(f"\n[trace] {out_path}", flush=True)
    if not any_present:
        print("[verdict] NO_DATA — no expected workspaces on disk", flush=True)
        return 3
    print(f"[verdict] {'PASS' if overall_ok else 'FAIL'}", flush=True)
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
