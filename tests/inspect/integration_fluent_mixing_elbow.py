"""L3 real-Fluent validation script — NOT a pytest test.

Runs two rounds against a real Fluent install:
  Round 1: no_gui (fast) — baseline 3 probes (ProcessMeta, TextStreamRules,
           PythonTraceback).
  Round 2: gui        — baseline + GUI probes (GuiDialog, Screenshot).

Each round executes the golden path + failure-injection matrix. Per-snippet
timeout guards against Fluent RPC hangs (the "dead loop" scenario itself).

Run:
    cd E:/simcli/sim-cli
    uv run python tests/inspect/integration_fluent_mixing_elbow.py [--no-gui|--gui|--both]

Output:
    tests/inspect/_run_outputs/mixing_elbow_<round>.json  (one per round)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).parent
RESULTS_DIR = HERE / "_run_outputs"
RESULTS_DIR.mkdir(exist_ok=True)

CASE_FILE = Path(
    os.environ.get("SIM_FLUENT_CASE", r"E:\simcli\sim-proj\mixing_elbow.cas.h5")
)


def banner(s):
    print("\n" + "=" * 70, flush=True)
    print(f"  {s}", flush=True)
    print("=" * 70, flush=True)


def dump_diags(out: dict, label: str) -> list[dict]:
    diags = out.get("diagnostics", [])
    arts = out.get("artifacts", [])
    print(f"[{label}] ok={out.get('ok')!r}  diagnostics={len(diags)}  artifacts={len(arts)}", flush=True)
    for i, d in enumerate(diags):
        print(f"  #{i+1} severity={d['severity']:<8} source={d['source']:<30} code={d['code']}", flush=True)
        msg = d["message"]
        if len(msg) > 220:
            msg = msg[:220] + "..."
        print(f"      message: {msg}", flush=True)
        if d.get("extra"):
            extra_preview = {k: v for k, v in d["extra"].items() if k != "match"}
            print(f"      extra  : {extra_preview}", flush=True)
    for i, a in enumerate(arts):
        print(f"  art#{i+1} role={a.get('role')} size={a.get('size')} path={a.get('path')}", flush=True)
    return diags


class _CallTimeout(Exception):
    pass


def call_with_timeout(fn, timeout_s: float):
    """Run `fn()` in a thread, return its result or raise _CallTimeout.

    We CANNOT safely kill the thread (it holds Fluent RPC state), so on
    timeout we mark the call as hung and raise. The caller must decide
    whether to continue with the same session (usually unsafe) or launch
    a fresh one.
    """
    box = {"ok": None, "exc": None, "done": False}

    def _worker():
        try:
            box["ok"] = fn()
        except BaseException as e:
            box["exc"] = e
        finally:
            box["done"] = True

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=timeout_s)
    if not box["done"]:
        raise _CallTimeout(f"call exceeded {timeout_s}s")
    if box["exc"]:
        raise box["exc"]
    return box["ok"]


def run_case(
    driver, code: str, label: str, *, timeout_s: float = 30.0
) -> dict:
    """driver.run() with a timeout. Returns the driver dict, or a synthetic
    {ok: False, diagnostics: [...hung...]} on timeout."""
    t0 = time.time()
    try:
        out = call_with_timeout(
            lambda: driver.run(code, label=label), timeout_s=timeout_s,
        )
        out["_wall"] = round(time.time() - t0, 2)
        return out
    except _CallTimeout:
        return {
            "ok": False,
            "label": label,
            "stdout": "", "stderr": "",
            "error": f"driver.run exceeded {timeout_s}s — likely Fluent RPC hang",
            "result": None,
            "_wall": round(time.time() - t0, 2),
            "_hung": True,
            "diagnostics": [{
                "severity": "error",
                "message": f"snippet hung past {timeout_s}s — no diagnostics could run",
                "source": "sim.inspect",
                "code": "sim.inspect.snippet_timeout",
                "extra": {},
            }],
            "artifacts": [],
        }


def run_round(ui_mode: str, *, label: str) -> dict:
    """Launch fluent in the given ui_mode, exec golden + failure matrix."""
    from sim.drivers.fluent.driver import PyFluentDriver

    results: dict = {
        "ui_mode": ui_mode,
        "label": label,
        "cases": {},
        "meta": {},
    }

    banner(f"launching Fluent 2024 R1 — ui_mode={ui_mode}, mode=solver")
    t0 = time.time()
    driver = PyFluentDriver()
    try:
        info = driver.launch(
            mode="solver", ui_mode=ui_mode, processors=2,
        )
    except Exception as exc:
        print(f"LAUNCH FAILED: {type(exc).__name__}: {exc}", flush=True)
        results["meta"]["launch_error"] = f"{type(exc).__name__}: {exc}"
        return results
    launch_t = round(time.time() - t0, 1)
    print(f"launch ok in {launch_t}s: {info}", flush=True)
    results["meta"]["launch_sec"] = launch_t
    results["meta"]["session_info"] = info
    results["meta"]["probes"] = [p.name for p in driver.probes]

    try:
        banner("golden A — read mixing_elbow case")
        out = run_case(
            driver,
            f'solver.file.read_case(file_name=r"{CASE_FILE}")\n'
            f'_result = {{"read_ok": True}}',
            "GP_read_case", timeout_s=60.0,
        )
        dump_diags(out, "GP_read_case")
        results["cases"]["GP_read_case"] = out

        banner("golden B — list velocity-inlet BC names")
        out = run_case(
            driver,
            'names = list(solver.setup.boundary_conditions.velocity_inlet.get_object_names())\n'
            '_result = {"vi_names": names}\n'
            'print("VI names:", names)',
            "GP_list_bcs", timeout_s=30.0,
        )
        dump_diags(out, "GP_list_bcs")
        results["cases"]["GP_list_bcs"] = out

        banner("F1 — wrong BC name 'inlet' (should be 'cold-inlet'/'hot-inlet')")
        out = run_case(
            driver,
            'solver.setup.boundary_conditions.velocity_inlet["inlet"].momentum.velocity.value = 9999',
            "F1_wrong_bc_name", timeout_s=30.0,
        )
        dump_diags(out, "F1")
        results["cases"]["F1_wrong_bc_name"] = out

        banner("F2 — access non-existent attribute on field_data")
        out = run_case(
            driver,
            'solver.fields.field_data.get_unobtainium("x")',
            "F2_bad_field_api", timeout_s=30.0,
        )
        dump_diags(out, "F2")
        results["cases"]["F2_bad_field_api"] = out

        banner("F3 — Python NameError (undefined_thing)")
        out = run_case(
            driver,
            'x = undefined_thing',
            "F3_name_error", timeout_s=10.0,
        )
        dump_diags(out, "F3")
        results["cases"]["F3_name_error"] = out

        banner("F4 — assign out-of-range viscous model name")
        out = run_case(
            driver,
            # Setting the viscous model to a bogus string should raise
            # immediately (DisallowedValuesError) — NO hang, unlike F4_orig
            # (write_case Z:/...) which would hang.
            'solver.setup.models.viscous.model = "not-a-real-model"',
            "F4_bad_model_name", timeout_s=20.0,
        )
        dump_diags(out, "F4")
        results["cases"]["F4_bad_model_name"] = out

        banner("F5 — GUI-only: if in gui mode, force a cortex error dialog")
        if ui_mode == "gui":
            # Fluent GUI pops an error dialog for some scheme commands. We
            # also just give GuiDialog+Screenshot probes a chance to fire.
            # Any transient dialog will be captured by the screenshot.
            out = run_case(
                driver,
                'solver.scheme_eval.scheme_eval("(ti-menu-load-string \\"surface/nonexistent-cmd\\")")',
                "F5_gui_scheme_error", timeout_s=30.0,
            )
            dump_diags(out, "F5")
            results["cases"]["F5_gui_scheme_error"] = out

    finally:
        banner("disconnecting")
        try:
            call_with_timeout(driver.disconnect, timeout_s=20.0)
        except Exception as exc:
            print(f"disconnect warn: {exc}", flush=True)

    out_path = RESULTS_DIR / f"mixing_elbow_{label}.json"
    out_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"\n[{label}] results → {out_path}", flush=True)
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["no_gui", "gui", "both"], default="no_gui")
    args = ap.parse_args()

    if not CASE_FILE.is_file():
        print(f"ABORT — case file not found: {CASE_FILE}")
        sys.exit(1)

    try:
        import ansys.fluent.core  # noqa: F401
    except Exception as exc:
        print(f"ABORT — ansys.fluent.core not importable: {exc}")
        sys.exit(1)

    rounds = []
    if args.mode in ("no_gui", "both"):
        rounds.append(("no_gui", "nogui_round"))
    if args.mode in ("gui", "both"):
        rounds.append(("gui", "gui_round"))

    for ui_mode, label in rounds:
        try:
            run_round(ui_mode, label=label)
        except Exception as exc:
            print(f"\n[{label}] FATAL: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
