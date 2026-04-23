"""Real COMSOL end-to-end simulation — Surface-Mount Package heat transfer.

Runs the 6-step sim-skills workflow at
  E:/simcli/sim-skills/comsol/base/workflows/surface_mount_package/
against a live COMSOL 6.4 GUI session, then extracts the chip-surface
maximum temperature via the Java evaluation API.

Reference result (from sim-skills README, COMSOL Application Library
model 847): chip max T ≈ 45.8 °C (our simplified pin geometry),
47.7 °C (original).

What "e2e" means here:
  1. Connect to COMSOL (GUI mode) — dismiss Cortex login via sim.gui
  2. Execute 00_create_geometry.py   (build ~20 solids)
  3. Execute 01_assign_materials.py  (copper/FR4/plastic/silicon/Al)
  4. Execute 02_setup_physics.py     (HT, convection, thin layers)
  5. Execute 03_generate_mesh.py     (~8.5k tets expected)
  6. Execute 04_solve.py             (stationary, ~6s)
  7. Extract numerical results       (max T in °C)
  8. Execute 05_plot_results.py      (create 3 plot groups, save .mph)
  9. Disconnect

Run:
    cd E:/simcli/sim-cli
    set COMSOL_USER=sim
    set COMSOL_PASSWORD=sim
    .venv/Scripts/python.exe tests/inspect/e2e_comsol_surface_mount.py

Output:
    tests/inspect/_run_outputs/comsol_surface_mount_e2e.json
    .sim/surface_mount_package.mph   (saved by step 05)
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
RESULTS_DIR = HERE / "_run_outputs"
RESULTS_DIR.mkdir(exist_ok=True)

WORKFLOW_DIR = Path(
    r"E:\simcli\sim-skills\comsol\base\workflows\surface_mount_package"
)
WORKDIR = Path(os.environ.get("SIM_DIR", r"E:\simcli\sim-cli\.sim")).resolve()

STEPS = [
    ("00_create_geometry.py",   "build 3D geometry (PC board + package + 16 pins + chip)"),
    ("01_assign_materials.py",  "assign Al/FR4/Plastic/Silicon/Copper to domains"),
    ("02_setup_physics.py",     "Heat Transfer in Solids + 20 mW source + thin copper layers"),
    ("03_generate_mesh.py",     "tet mesh with local refinement (~8.5k elems)"),
    ("04_solve.py",             "run stationary study"),
    ("05_plot_results.py",      "create 3 plot groups + save .mph"),
]


def banner(s: str) -> None:
    print("\n" + "=" * 78, flush=True)
    print(f"  {s}", flush=True)
    print("=" * 78, flush=True)


def run_step(driver, label: str, code: str, timeout_s: float) -> dict:
    t0 = time.time()
    out = driver.run(code, label=label, timeout_s=timeout_s)
    wall = round(time.time() - t0, 1)
    ok = out.get("ok")
    err = out.get("error")
    result = out.get("result")
    print(f"  → ok={ok}  wall={wall}s  result={str(result)[:120]}", flush=True)
    if err:
        print(f"     error: {err}", flush=True)
    # show last stdout line (usually helpful)
    stdout = (out.get("stdout") or "").strip().splitlines()
    if stdout:
        print(f"     stdout[-1]: {stdout[-1][:160]}", flush=True)
    return {"label": label, "wall_sec": wall, "ok": ok,
            "result": result, "error": err,
            "stdout_tail": stdout[-3:] if stdout else []}


def main() -> int:
    try:
        import mph  # noqa: F401
    except Exception as exc:
        print(f"ABORT — mph not importable: {exc}")
        return 1
    os.environ.setdefault("COMSOL_USER", "sim")
    os.environ.setdefault("COMSOL_PASSWORD", "sim")

    from sim.drivers.comsol.driver import ComsolDriver
    driver = ComsolDriver()
    driver._sim_dir = WORKDIR
    driver._port = int(os.environ.get("SIM_COMSOL_PORT", "2037"))

    banner("COMSOL Surface-Mount Package — real e2e")
    print(f" workflow dir : {WORKFLOW_DIR}", flush=True)
    print(f" workdir      : {WORKDIR}", flush=True)

    t0 = time.time()
    info = driver.launch(mode="solver", ui_mode="gui", processors=2)
    launch_sec = round(time.time() - t0, 1)
    print(f"[launch] ok in {launch_sec}s  port={driver._port}  "
          f"model_tag={info.get('model_tag')}", flush=True)

    trace: dict = {
        "launch_sec": launch_sec,
        "port": driver._port,
        "steps": [],
    }

    try:
        # ── dismiss Cortex login via gui so the GUI is interactive ─────────
        banner("Dismiss Cortex login (Phase 3 gui actuation)")
        dismiss = driver.run(
            'dlg = gui.find(title_contains="连接到", timeout_s=8)\n'
            'if dlg is None:\n'
            '    dlg = gui.find(title_contains="Connect to COMSOL", timeout_s=3)\n'
            'if dlg is None:\n'
            '    _result = {"ok": True, "already": True}\n'
            'else:\n'
            '    r = dlg.click("确定")\n'
            '    if not r.get("ok"):\n'
            '        r = dlg.click("OK")\n'
            '    gui.wait_until_window_gone("连接到", timeout_s=15)\n'
            '    _result = {"ok": r.get("ok"), "click": r}',
            label="dismiss_login", timeout_s=30,
        )
        print(f"  → {dismiss.get('result')}", flush=True)
        trace["dismiss_login"] = dismiss.get("result")

        # ── 6 workflow steps ────────────────────────────────────────────────
        # Prefix each step with the workflow dir so relative imports / file
        # refs in the helpers directory resolve.
        sys_path_prefix = (
            f"import sys as _sys\n"
            f"_p = r'{WORKFLOW_DIR}'\n"
            f"if _p not in _sys.path:\n"
            f"    _sys.path.insert(0, _p)\n"
        )

        total_step_sec = 0.0
        solve_ok = False
        for fname, desc in STEPS:
            banner(f"Step {fname} — {desc}")
            script_path = WORKFLOW_DIR / fname
            code = sys_path_prefix + script_path.read_text(encoding="utf-8")
            step_out = run_step(
                driver,
                label=fname.replace(".py", ""),
                code=code,
                timeout_s=180.0 if "solve" in fname or "mesh" in fname else 60.0,
            )
            trace["steps"].append(step_out)
            total_step_sec += step_out["wall_sec"]
            if not step_out["ok"]:
                banner(f"STEP FAILED — aborting downstream: {fname}")
                break
            # Between solve and plot: try early MaxMinVolume extraction.
            # Before plot groups exist, the result context might be cleaner.
            if fname == "04_solve.py":
                solve_ok = True
                banner("Early extract — MaxMinVolume before plot groups")
                early_code = """\
import jpype as _jp
JS = _jp.JArray(_jp.JString)
ds_tags = [str(t) for t in model.result().dataset().tags()]
ds_tag = ds_tags[0] if ds_tags else "dset1"
print(f"early: datasets={ds_tags}")
_early_max = None
_early_method = None
_early_diag = []
# Try MaxMinVolume without selection (default = all)
try:
    for _t in list(model.result().numerical().tags()):
        if str(_t) == "_emm":
            model.result().numerical().remove("_emm")
    mm = model.result().numerical().create("_emm", "MaxMinVolume")
    mm.set("data", ds_tag)
    mm.set("expr", JS(["T-273.15"]))
    _mat = [[float(v) for v in row] for row in mm.computeResult()]
    _early_max = _mat[0][0]
    model.result().numerical().remove("_emm")
    _early_method = "MaxMinVolume_no_selection"
except Exception as _e:
    _early_diag.append(f"MaxMinVolume_no_selection FAIL: {str(_e)[:120]}")
# Try export
if _early_max is None:
    import os, tempfile
    _ep = os.path.join(tempfile.gettempdir(), "sim_comsol_early.txt")
    try:
        _ex = model.result().export().create("_ex", "Data")
        _ex.set("data", ds_tag)
        _ex.set("expr", JS(["T-273.15"]))
        _ex.set("filename", _ep)
        _ex.run()
        model.result().export().remove("_ex")
        _vals = []
        with open(_ep) as _f:
            for _line in _f:
                _line = _line.strip()
                if not _line or _line.startswith("%"):
                    continue
                try:
                    _vals.append(float(_line.split()[-1]))
                except Exception:
                    pass
        if _vals:
            _early_max = max(_vals)
            _early_method = "export.Data"
        try: os.remove(_ep)
        except: pass
    except Exception as _e2:
        _early_diag.append(f"export.Data FAIL: {str(_e2)[:120]}")
print(f"early Tmax={_early_max} method={_early_method}")
print(f"early diag: {_early_diag}")
_result = {"early_max_T_C": _early_max, "early_method": _early_method,
           "early_diag": _early_diag}
"""
                early_out = run_step(driver, "early_extract", early_code, timeout_s=60)
                trace["early_extract"] = early_out

        # ── Extract numerical result: chip max temperature ──────────────────
        banner("Extract result — chip surface max temperature")
        extract_code = """\
import jpype as _jp
import os, tempfile
JS = _jp.JArray(_jp.JString)

ds_tags = [str(t) for t in model.result().dataset().tags()]
print("datasets:", ds_tags)
ds_tag = ds_tags[0] if ds_tags else "dset1"

max_T_C = None
min_T_C = None
max_loc = None
_method = None
_diag = []

# Method 1: Export temperature field — correct attr is "data" (not "dataset")
_exp_path = os.path.join(tempfile.gettempdir(), "sim_comsol_T.txt")
try:
    for _t in list(model.result().export().tags()):
        if str(_t) == "_Texp":
            model.result().export().remove("_Texp")
    _exp = model.result().export().create("_Texp", "Data")
    _exp.set("data", ds_tag)
    _exp.set("expr", JS(["T-273.15"]))
    _exp.set("filename", _exp_path)
    _exp.run()
    model.result().export().remove("_Texp")
    _vals = []
    with open(_exp_path, "r") as _f:
        for _line in _f:
            _line = _line.strip()
            if not _line or _line.startswith("%"):
                continue
            try:
                _vals.append(float(_line.split()[-1]))
            except Exception:
                pass
    if _vals:
        max_T_C = max(_vals)
        min_T_C = min(_vals)
        _method = "export.Data"
        _diag.append(f"export: {len(_vals)} nodes, max={max_T_C:.3f}")
    try:
        os.remove(_exp_path)
    except Exception:
        pass
except Exception as _e1:
    _diag.append(f"export.Data FAIL: {str(_e1)[:120]}")

# Method 2: MaxMinVolume
if max_T_C is None:
    try:
        for _t in list(model.result().numerical().tags()):
            if str(_t) in ("_mm",):
                model.result().numerical().remove(_t)
        _mm = model.result().numerical().create("_mm", "MaxMinVolume")
        _mm.set("data", ds_tag)
        _mm.set("expr", JS(["T-273.15"]))
        _mm.selection().all()
        _mat = [[float(v) for v in row] for row in _mm.computeResult()]
        max_T_C = _mat[0][0]
        min_T_C = _mat[1][0] if len(_mat) > 1 else None
        max_loc = _mat[0][1:4] if len(_mat[0]) >= 4 else None
        _method = "MaxMinVolume"
        model.result().numerical().remove("_mm")
    except Exception as _e2:
        _diag.append(f"MaxMinVolume FAIL: {str(_e2)[:120]}")

print(f"Tmax = {max_T_C} degC  (method={_method})")
if min_T_C is not None:
    print(f"Tmin = {min_T_C} degC")
print("Reference chip max T (COMSOL Appl Lib 847): 45.80 degC")
print(f"diag: {_diag}")

_result = {
    "max_T_C": max_T_C,
    "min_T_C": min_T_C,
    "max_location_m": max_loc,
    "method": _method,
    "reference_max_T_C": 45.8,
    "dataset_used": ds_tag,
    "diag": _diag,
}
"""
        extract = run_step(driver, "extract_result", extract_code, timeout_s=60)
        trace["extract"] = extract

    finally:
        banner("disconnect")
        try:
            r = driver.disconnect()
            print(f"  disconnect = {r}", flush=True)
        except Exception as exc:
            print(f"  disconnect warn: {exc}", flush=True)

    # ── verdict ───────────────────────────────────────────────────────────
    all_steps_ok = all(s.get("ok") for s in trace["steps"])
    extract_ok = (trace.get("extract") or {}).get("ok")
    max_T = ((trace.get("extract") or {}).get("result") or {}).get("max_T_C")
    # Fallback to early_extract (taken before plot groups) if late extract failed
    if max_T is None:
        max_T = ((trace.get("early_extract") or {}).get("result") or {}).get("early_max_T_C")

    banner("RESULT SUMMARY")
    print(f"  launch_sec           : {launch_sec}", flush=True)
    print(f"  steps run            : {len(trace['steps'])}/6", flush=True)
    for s in trace["steps"]:
        flag = "[ok]" if s["ok"] else "[FAIL]"
        print(f"    {flag:<6} {s['label']:<22} {s['wall_sec']:>6.1f}s", flush=True)
    print(f"  extract ok           : {extract_ok}", flush=True)
    if max_T is not None:
        delta = max_T - 45.8
        print(f"  chip max T           : {max_T:.2f} °C  "
              f"(ref 45.8 °C; Δ={delta:+.2f})", flush=True)

    verdict = all_steps_ok and extract_ok and max_T is not None
    banner(f"VERDICT — real COMSOL e2e: {'PASS' if verdict else 'FAIL'}")

    out_path = RESULTS_DIR / "comsol_surface_mount_e2e.json"
    out_path.write_text(json.dumps(trace, indent=2, default=str))
    print(f"\n[trace] {out_path}", flush=True)

    return 0 if verdict else 3


if __name__ == "__main__":
    sys.exit(main())
