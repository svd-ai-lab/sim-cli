"""L3 real-COMSOL agent-dialogue trace — 9-channel cross-driver validation.

Mirrors tests/inspect/integration_fluent_agent_dialogue.py but against a
real COMSOL 6.4 session (via MPh + JPype + comsolmphserver).

Run:
    cd E:/simcli/sim-cli
    # Cached creds must exist first — `comsolmphserver.exe -login force` once,
    # enter sim/sim (or override via env vars):
    set COMSOL_USER=sim
    set COMSOL_PASSWORD=sim
    uv run python tests/inspect/integration_comsol_agent_dialogue.py [--mode gui|desktop|no_gui]

Output:
    tests/inspect/_run_outputs/comsol_agent_dialogue_trace.{json,log}
    screenshots per turn in .sim/screenshots/
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
RESULTS_DIR = HERE / "_run_outputs"
RESULTS_DIR.mkdir(exist_ok=True)

# Default case: bundled COMSOL example, small + generic physics
COMSOL_ROOT = Path(r"E:/Program Files (x86)/COMSOL64/Multiphysics")
DEFAULT_MPH = COMSOL_ROOT / "applications" / "ACDC_Module" / \
    "Electromagnetic_Heating" / "heating_circuit.mph"
CASE_FILE = Path(os.environ.get("SIM_COMSOL_CASE", str(DEFAULT_MPH)))
WORKDIR = Path(os.environ.get("SIM_DIR", r"E:\simcli\sim-cli\.sim")).resolve()


# Channel classification (parallel to Fluent trace script)
CHANNEL_RULES: list[tuple[str, str]] = [
    ("process",            "#1 ProcessMeta"),
    ("sim.runtime",        "#1+ RuntimeTimeout"),
    ("stderr",             "#2 stderr regex"),
    ("stdout:json",        "#3 StdoutJsonTail"),
    ("traceback",          "#3+ PythonTraceback"),
    ("sdk:attr",           "#4 SdkAttribute"),
    ("gui:dialog",         "#8a GuiDialog"),
    ("gui:screenshot",     "#8b Screenshot"),
    ("workdir",            "#9 WorkdirDiff"),
    ("sim.inspect",        "probe infra"),
]


def classify(diag: dict) -> str:
    src = diag.get("source", "")
    code = diag.get("code", "")
    # Channel #5 — comsol.* upgrades come from DomainExceptionMapProbe
    if code.startswith("comsol.") and src == "traceback":
        return "#5 DomainExceptionMap"
    for prefix, label in CHANNEL_RULES:
        if src.startswith(prefix):
            return label
    return "(other)"


def banner(s):
    print("\n" + "=" * 78, flush=True)
    print(f"  {s}", flush=True)
    print("=" * 78, flush=True)


def run_turn(driver, *, agent_intent: str, code: str, label: str,
             timeout_s: float = 60.0) -> dict:
    print("\n" + "=" * 78, flush=True)
    print(f">> Agent turn #{label}", flush=True)
    print(f"  Intent : {agent_intent}", flush=True)
    print("  Snippet:", flush=True)
    for line in code.strip().splitlines():
        print(f"    |{line}", flush=True)
    t0 = time.time()
    try:
        out = driver.run(code, label=label, timeout_s=timeout_s)
    except Exception as exc:
        out = {
            "ok": False, "label": label, "error": str(exc),
            "stdout": "", "stderr": "", "result": None,
            "diagnostics": [{
                "severity": "error",
                "message": f"driver.run raised {type(exc).__name__}: {exc}",
                "source": "sim.inspect", "code": "sim.inspect.driver_run_crashed",
                "extra": {},
            }],
            "artifacts": [],
        }
    wall = round(time.time() - t0, 2)

    by_channel: dict[str, list[dict]] = defaultdict(list)
    for d in out.get("diagnostics", []):
        by_channel[classify(d)].append(d)

    print(f"\n  Result : ok={out.get('ok')}  wall={wall}s  "
          f"diagnostics={len(out.get('diagnostics', []))}  "
          f"artifacts={len(out.get('artifacts', []))}", flush=True)
    if out.get("result") is not None:
        r_preview = repr(out["result"])[:150]
        print(f"  _result: {r_preview}", flush=True)

    print("\n  Inspect by channel:", flush=True)
    for label_ch in [lbl for _, lbl in CHANNEL_RULES] + ["#5 DomainExceptionMap", "(other)"]:
        diags = by_channel.get(label_ch, [])
        if not diags:
            continue
        print(f"    {label_ch}:", flush=True)
        for d in diags:
            msg = d["message"]
            if len(msg) > 180:
                msg = msg[:177] + "..."
            print(f"      [{d['severity']:<7}] code={d['code']}", flush=True)
            print(f"                message: {msg}", flush=True)

    arts = out.get("artifacts", [])
    if arts:
        print("\n  Artifacts:", flush=True)
        for a in arts:
            print(f"    role={a.get('role'):<15} size={a.get('size')} "
                  f"path={a.get('path')}", flush=True)

    return {
        "label": label, "intent": agent_intent,
        "code": code.strip(), "wall_sec": wall,
        "ok": out.get("ok"), "result": out.get("result"),
        "diagnostics": out.get("diagnostics", []),
        "artifacts": out.get("artifacts", []),
        "by_channel": dict(by_channel),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["gui", "desktop", "no_gui"], default="gui")
    args = ap.parse_args()

    if not CASE_FILE.is_file():
        print(f"ABORT — COMSOL case file not found: {CASE_FILE}")
        sys.exit(1)

    try:
        import mph  # noqa: F401
    except Exception as exc:
        print(f"ABORT — mph not importable: {exc}")
        sys.exit(1)

    # Ensure creds for comsolmphserver -login auto
    os.environ.setdefault("COMSOL_USER", "sim")
    os.environ.setdefault("COMSOL_PASSWORD", "sim")

    # Wipe prior run artifacts so #9 WorkdirDiff has clean baselines
    shots = WORKDIR / "screenshots"
    if shots.exists():
        for p in shots.glob("comsol_shot_*.png"):
            try:
                p.unlink()
            except OSError:
                pass
    for stem in ("comsol_run_v1.mph",):
        try:
            (WORKDIR / stem).unlink()
        except (OSError, FileNotFoundError):
            pass

    from sim.drivers.comsol.driver import ComsolDriver, _default_comsol_probes
    driver = ComsolDriver()
    driver._sim_dir = WORKDIR
    # Default port 2036 is usually in use (user's ComsolUI holds it).
    # Use a higher port to avoid collision.
    driver._port = int(os.environ.get("SIM_COMSOL_PORT", "2037"))

    banner(f"COMSOL agent-dialogue trace — ui_mode={args.mode}")
    print(f" case    : {CASE_FILE}", flush=True)
    print(f" workdir : {WORKDIR}", flush=True)

    print("\n[launch] starting comsolmphserver + JPype ...", flush=True)
    t0 = time.time()
    info = driver.launch(
        mode="solver", ui_mode=args.mode, processors=2,
    )
    launch_sec = round(time.time() - t0, 1)
    print(f"[launch] ok in {launch_sec}s: {info}", flush=True)

    # Swap in GUI probes now that we know ui_mode.
    # NOTE: we also enable GUI probes in no_gui mode here because the user
    # may already have a ComsolUI window open (common Phase-2-verification
    # situation — we want the trace to show #8a/#8b can see it).
    enable_gui = True
    driver.probes = _default_comsol_probes(enable_gui=enable_gui)
    print(f"[launch] driver.probes = {[p.name for p in driver.probes]}", flush=True)

    turns: list[dict] = []

    try:
        # ── T1: load heating_circuit.mph ───────────────────────────────────
        turns.append(run_turn(
            driver,
            agent_intent="Load the heating_circuit.mph case into the session.",
            code=(
                f'ModelUtil.loadCopy("Model1", r"{CASE_FILE}")\n'
                f'model = ModelUtil.model("Model1")\n'
                f'_result = {{"case": r"{CASE_FILE}"}}'
            ),
            label="T1_load_case",
            timeout_s=90.0,
        ))

        # ── T2: query model structure (SDK readers on real model) ──────────
        turns.append(run_turn(
            driver,
            agent_intent="Query model's physics, study, material counts via "
                         "SDK probe #4. Print a JSON summary too — exercises "
                         "StdoutJsonTail #3.",
            code=(
                'phys = list(model.physics().tags())\n'
                'std = list(model.study().tags())\n'
                'mat = list(model.material().tags())\n'
                'import json as _j\n'
                'print(_j.dumps({"physics": phys, "study": std, "material": mat}))\n'
                '_result = {"physics": phys, "study": std, "material": mat}'
            ),
            label="T2_query_structure",
            timeout_s=30.0,
        ))

        # ── T3: parameter mutation via Java API ────────────────────────────
        turns.append(run_turn(
            driver,
            agent_intent="Set a scalar parameter (Voltage or similar) via the "
                         "Java-style API. Exercises SDK attr + stdout.",
            code=(
                '# heating_circuit has a parameter "V_in" (applied voltage)\n'
                'params = model.param()\n'
                'old = params.get("V_in") if "V_in" in list(params.varnames()) else None\n'
                'if old is not None:\n'
                '    params.set("V_in", "0.25[V]")\n'
                '    _result = {"changed": "V_in", "new": "0.25[V]", "old": str(old)}\n'
                'else:\n'
                '    _result = {"note": "V_in not found; parameter-set skipped",\n'
                '               "varnames": list(params.varnames())[:8]}\n'
                'import json as _j\nprint(_j.dumps(_result))'
            ),
            label="T3_mutate_parameter",
            timeout_s=30.0,
        ))

        # ── T4: DELIBERATE bad feature tag → #3+ traceback + #5 map ────────
        turns.append(run_turn(
            driver,
            agent_intent="(typo) try reading a feature with a tag that doesn't "
                         "exist. Expect #3+ python exception + #5 upgrade to "
                         "comsol.feature.not_found.",
            code=(
                'bad = model.feature("this-tag-does-not-exist").getString("type")\n'
                '_result = bad'
            ),
            label="T4_bad_feature_tag",
            timeout_s=20.0,
        ))

        # ── T5: save model to a new file (#9 WorkdirDiff catches .mph) ─────
        save_path = (WORKDIR / "comsol_run_v1.mph").as_posix()
        turns.append(run_turn(
            driver,
            agent_intent="Save the model to a new .mph file — #9 WorkdirDiff "
                         "should emit role=comsol-model artifact.",
            code=(
                f'model.save(r"{save_path}")\n'
                f'_result = {{"saved": r"{save_path}"}}'
            ),
            label="T5_save_model",
            timeout_s=60.0,
        ))

        # ── T6: trivial Python error → #3+ python.NameError ────────────────
        turns.append(run_turn(
            driver,
            agent_intent="Trigger a Python NameError to confirm PythonTracebackProbe "
                         "#3+ works the same as on Fluent.",
            code=(
                'x = undefined_thing_in_comsol_session'
            ),
            label="T6_name_error",
            timeout_s=10.0,
        ))

        # ── T7: drill into a non-existent component (Java exception path) ──
        turns.append(run_turn(
            driver,
            agent_intent="Drill into a component tag that doesn't exist — the "
                         "Java side throws, traceback should mention a COMSOL "
                         "exception class. Probe #5 should upgrade if the "
                         "regex matches.",
            code=(
                '# heating_circuit only has "comp1"; ask for non-existent\n'
                'bad = model.component("comp-does-not-exist")\n'
                'bad.physics("solid")\n'
                '_result = "should not reach"'
            ),
            label="T7_bad_component",
            timeout_s=20.0,
        ))

    finally:
        print("\n[disconnect] tearing down COMSOL session ...", flush=True)
        try:
            driver.disconnect()
        except Exception as exc:
            print(f"  disconnect warn: {exc}", flush=True)

    # Per-channel summary
    print("\n" + "=" * 78, flush=True)
    print(" COMSOL PER-CHANNEL HIT REPORT", flush=True)
    print("=" * 78, flush=True)
    hit = {label: [] for _, label in CHANNEL_RULES}
    hit["#5 DomainExceptionMap"] = []
    hit["(other)"] = []
    for turn in turns:
        for d in turn["diagnostics"]:
            ch = classify(d)
            hit.setdefault(ch, []).append({
                "turn": turn["label"], "severity": d["severity"],
                "code": d["code"],
            })
        shot_paths = {d["extra"].get("path") for d in turn["diagnostics"]
                       if d.get("code") == "sim.screenshot.captured"}
        for a in turn["artifacts"]:
            if a.get("path") in shot_paths:
                continue
            hit["#9 WorkdirDiff"].append({
                "turn": turn["label"], "severity": "info",
                "code": f"artifact.role={a.get('role')}",
            })

    for ch, entries in hit.items():
        if not entries:
            print(f"  {ch:<30}: (no hits)", flush=True)
            continue
        by_turn = defaultdict(int)
        for e in entries:
            by_turn[e["turn"]] += 1
        breakdown = ", ".join(f"{t}x{n}" for t, n in by_turn.items())
        sevs = defaultdict(int)
        codes: set[str] = set()
        for e in entries:
            sevs[e["severity"]] += 1
            codes.add(e["code"])
        print(f"  {ch:<30}: {len(entries)} hits "
              f"[{breakdown}]  severities={dict(sevs)}", flush=True)
        for c in sorted(codes):
            print(f"       {c}", flush=True)

    out_path = RESULTS_DIR / "comsol_agent_dialogue_trace.json"
    out_path.write_text(json.dumps({
        "ui_mode": args.mode,
        "launch_sec": launch_sec,
        "driver_probes": [p.name for p in driver.probes],
        "case_file": str(CASE_FILE),
        "turns": turns,
    }, indent=2, default=str))
    print(f"\n[trace] {out_path}", flush=True)


if __name__ == "__main__":
    main()
