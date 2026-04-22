"""L3 real-Fluent agent-dialogue trace — exercises all 9 channels.

Simulates a multi-turn agent conversation against a live Fluent GUI session
and prints, per turn:
  • what the "agent" is trying to do
  • the snippet being executed
  • the diagnostics list, grouped by channel, with the per-channel code

Run:
    cd E:/simcli/sim-cli
    uv run python tests/inspect/integration_fluent_agent_dialogue.py

Output:
    tests/inspect/_run_outputs/agent_dialogue_trace.json
    tests/inspect/_run_outputs/agent_dialogue_trace.log
    plus per-turn screenshots in .sim/screenshots/
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
RESULTS_DIR = HERE / "_run_outputs"
RESULTS_DIR.mkdir(exist_ok=True)

CASE_FILE = Path(
    os.environ.get("SIM_FLUENT_CASE", r"E:\simcli\sim-proj\mixing_elbow.cas.h5")
)
WORKDIR = Path(os.environ.get("SIM_DIR", r"E:\simcli\sim-cli\.sim")).resolve()


# ── Channel classification (one dict source of truth) ──────────────────────────
# Map Diagnostic.source (or prefix thereof) → channel label used in the trace.
CHANNEL_RULES: list[tuple[str, str]] = [
    ("process",                    "#1 ProcessMeta"),
    ("stderr",                     "#2 stderr regex"),
    ("stdout:json",                "#3 StdoutJsonTail"),
    ("traceback",                  "#3+ PythonTraceback"),
    ("sdk:attr",                   "#4 SdkAttribute"),
    ("tui:stdout",                 "#6 TUI echo"),
    ("log:session.trn",            "#7 Log file (transcript)"),
    ("gui:dialog",                 "#8a GuiDialog"),
    ("gui:screenshot",             "#8b Screenshot"),
    ("workdir",                    "#9 WorkdirDiff"),
    ("sim.inspect",                "probe infra"),
]


def classify(diag: dict) -> str:
    """Map a diagnostic's source+code to a channel label."""
    src = diag.get("source", "")
    code = diag.get("code", "")
    # Channel 5 (exception map): code starts with fluent. but NOT from tui/rpc
    if code.startswith("fluent.sdk.") or code.startswith("fluent.rpc."):
        if src == "traceback":
            return "#5 FluentExceptionMap"
    for prefix, label in CHANNEL_RULES:
        if src.startswith(prefix):
            return label
    return "(other)"


# ── timeout wrapper (same as before) ───────────────────────────────────────────

class _CallTimeout(Exception):
    pass


def call_with_timeout(fn, timeout_s: float):
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


def run_turn(driver, *, agent_intent: str, code: str, label: str,
             timeout_s: float = 60.0) -> dict:
    """Execute one 'agent turn' against Fluent, collect full trace."""
    print("\n" + "=" * 78, flush=True)
    print(f">> Agent turn #{label}", flush=True)
    print(f"  Intent : {agent_intent}", flush=True)
    print("  Snippet:", flush=True)
    for line in code.strip().splitlines():
        print(f"    |{line}", flush=True)
    t0 = time.time()
    try:
        out = call_with_timeout(
            lambda: driver.run(code, label=label), timeout_s=timeout_s,
        )
    except _CallTimeout:
        out = {
            "ok": False, "label": label, "error": "timeout", "stdout": "",
            "stderr": "", "result": None,
            "diagnostics": [{
                "severity": "error",
                "message": f"driver.run exceeded {timeout_s}s — Fluent RPC hang",
                "source": "sim.inspect", "code": "sim.inspect.snippet_timeout",
                "extra": {},
            }],
            "artifacts": [],
        }
    wall = round(time.time() - t0, 2)

    # Group by channel
    by_channel: dict[str, list[dict]] = defaultdict(list)
    for d in out.get("diagnostics", []):
        by_channel[classify(d)].append(d)

    print(f"\n  Result : ok={out.get('ok')}  wall={wall}s  "
          f"diagnostics={len(out.get('diagnostics', []))}  "
          f"artifacts={len(out.get('artifacts', []))}", flush=True)
    if out.get("result") is not None:
        r_preview = repr(out["result"])
        if len(r_preview) > 150:
            r_preview = r_preview[:147] + "..."
        print(f"  _result: {r_preview}", flush=True)

    # Per-channel breakdown
    print("\n  Inspect by channel:", flush=True)
    for label_ch in [lbl for _, lbl in CHANNEL_RULES] + ["#5 FluentExceptionMap", "(other)"]:
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

    # Artifacts
    arts = out.get("artifacts", [])
    if arts:
        print("\n  Artifacts:", flush=True)
        for a in arts:
            print(f"    role={a.get('role'):<12} size={a.get('size')} "
                  f"path={a.get('path')}", flush=True)

    return {
        "label": label,
        "intent": agent_intent,
        "code": code.strip(),
        "wall_sec": wall,
        "ok": out.get("ok"),
        "result": out.get("result"),
        "diagnostics": out.get("diagnostics", []),
        "artifacts": out.get("artifacts", []),
        "by_channel": {k: v for k, v in by_channel.items()},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["no_gui", "gui"], default="gui",
                    help="Fluent UI mode (gui enables #8a/#8b channels)")
    args = ap.parse_args()

    if not CASE_FILE.is_file():
        print(f"ABORT — case file not found: {CASE_FILE}")
        sys.exit(1)
    try:
        import ansys.fluent.core  # noqa: F401
    except Exception as exc:
        print(f"ABORT — ansys.fluent.core not importable: {exc}")
        sys.exit(1)

    # Wipe workdir state from earlier runs so per-turn diff is clean.
    # Critical for #9 WorkdirDiff: if run_v1.cas.h5 already exists in
    # workdir_before, T5 won't "see" it as new.
    shots = WORKDIR / "screenshots"
    if shots.exists():
        for p in shots.glob("fluent_shot_*.png"):
            try:
                p.unlink()
            except OSError:
                pass
    for stem in ("run_v1.cas.h5", "run_v1.dat.h5", "session.trn"):
        try:
            (WORKDIR / stem).unlink()
        except (OSError, FileNotFoundError):
            pass

    from sim.drivers.fluent.driver import PyFluentDriver
    driver = PyFluentDriver(sim_dir=WORKDIR)

    print("=" * 78, flush=True)
    print(f" agent-dialogue trace — ui_mode={args.mode}", flush=True)
    print(f" case     : {CASE_FILE}", flush=True)
    print(f" workdir  : {WORKDIR}", flush=True)
    print("=" * 78, flush=True)

    print("\n[launch] starting Fluent ...", flush=True)
    t0 = time.time()
    info = driver.launch(mode="solver", ui_mode=args.mode, processors=2)
    launch_sec = round(time.time() - t0, 1)
    print(f"[launch] ok in {launch_sec}s: {info}", flush=True)
    print(f"[launch] driver.probes = {[p.name for p in driver.probes]}", flush=True)

    turns: list[dict] = []

    try:
        # ── turn 1: read case ──────────────────────────────────────────────
        turns.append(run_turn(
            driver,
            agent_intent="Load the mixing_elbow case so I can inspect it.",
            code=(
                f'solver.file.read_case(file_name=r"{CASE_FILE}")\n'
                f'_result = {{"case": r"{CASE_FILE}"}}'
            ),
            label="T1_read_case",
            timeout_s=90.0,
        ))

        # ── turn 2: start transcript + list BCs (SDK) ──────────────────────
        trn_path = (WORKDIR / "session.trn").as_posix()
        turns.append(run_turn(
            driver,
            agent_intent="Open a transcript file so every future step logs. "
                         "Then list the velocity-inlet boundary names.",
            code=(
                f'solver.file.start_transcript(file_name=r"{trn_path}")\n'
                f'names = list(solver.setup.boundary_conditions.velocity_inlet.get_object_names())\n'
                f'print("VI names:", names)\n'
                f'import json as _j\nprint(_j.dumps({{"vi_names": names}}))\n'
                f'_result = {{"vi_names": names}}'
            ),
            label="T2_transcript_and_bcs",
            timeout_s=30.0,
        ))

        # ── turn 3: switch turbulence model + iterate (SDK + TUI) ──────────
        turns.append(run_turn(
            driver,
            agent_intent="Switch turbulence to k-epsilon, then run 5 iterations "
                         "via the TUI. Two channels should light up: #4 (SDK "
                         "attribute re-read on new model) and #6 (TUI echo).",
            code=(
                'solver.setup.models.viscous.model = "k-epsilon"\n'
                'solver.setup.models.energy.enabled = True\n'
                'solver.solution.initialization.hybrid_initialize()\n'
                'solver.tui.solve.iterate(5)\n'
                '_result = {"model_after": str(solver.setup.models.viscous.model()),\n'
                '           "energy": solver.setup.models.energy.enabled()}'
            ),
            label="T3_change_model_and_iterate",
            timeout_s=120.0,
        ))

        # ── turn 4: deliberate bad BC name (exception map upgrade) ─────────
        turns.append(run_turn(
            driver,
            agent_intent="(typo) try setting inlet velocity on a wrong BC name "
                         "'inlet'. Should produce #3+ traceback AND #5 "
                         "fluent.sdk.attr_not_found upgrade.",
            code=(
                'solver.setup.boundary_conditions.velocity_inlet["inlet"]'
                '.momentum.velocity.value = 5.0'
            ),
            label="T4_bad_bc_name",
            timeout_s=20.0,
        ))

        # ── turn 5: write case+data (new files → #9) ───────────────────────
        save_stem = (WORKDIR / "run_v1").as_posix()
        turns.append(run_turn(
            driver,
            agent_intent="Save the current case and data to disk. Expect #9 "
                         "WorkdirDiff to see new .cas.h5 / .dat.h5 files.",
            code=(
                f'solver.file.write_case_data(file_name=r"{save_stem}")\n'
                f'_result = {{"saved_stem": r"{save_stem}"}}'
            ),
            label="T5_save_run_v1",
            timeout_s=60.0,
        ))

        # ── turn 6: call TUI with bad arg (#6 error + #3+) ─────────────────
        turns.append(run_turn(
            driver,
            agent_intent="Try a display that references a non-existent surface. "
                         "Expect #6 TUI echo to catch Fluent's text-level Error:.",
            code=(
                'solver.tui.display.objects.display("does-not-exist")'
            ),
            label="T6_bad_tui_call",
            timeout_s=20.0,
        ))

        # ── turn 7: scheme_eval to force TUI echo into stdout ──────────────
        # pyfluent's scheme_eval returns the scheme result, but (ti-menu-load-string
        # ...) also writes the TUI's own echo to stdout — which is exactly what
        # our #6 TextStreamRulesProbe(source=tui:stdout) reads.
        turns.append(run_turn(
            driver,
            agent_intent="Drive TUI via scheme_eval — should print Fluent's TUI "
                         "echo to stdout, lighting #6. Use a typo'd command that "
                         "prompts Fluent to print 'Error Object:' back.",
            code=(
                'result = solver.scheme_eval.scheme_eval('
                '"(ti-menu-load-string \\"surface/rename-surface this-surface-does-not-exist renamed-surface\\")"'
                ')\n'
                '_result = {"scheme_ret": str(result)[:200]}'
            ),
            label="T7_scheme_tui_echo",
            timeout_s=20.0,
        ))

    finally:
        print("\n[disconnect] tearing down Fluent session ...", flush=True)
        try:
            call_with_timeout(driver.disconnect, timeout_s=20.0)
        except Exception as exc:
            print(f"  disconnect warn: {exc}", flush=True)

    # ── per-channel summary table ──────────────────────────────────────────
    # Note: #9 WorkdirDiff emits only Artifacts (no Diagnostics) — count them
    # separately. Artifacts from ScreenshotProbe are already attributed to #8b.
    print("\n" + "=" * 78, flush=True)
    print(" PER-CHANNEL HIT REPORT", flush=True)
    print("=" * 78, flush=True)
    hit = {label: [] for _, label in CHANNEL_RULES}
    hit["#5 FluentExceptionMap"] = []
    hit["(other)"] = []
    for turn in turns:
        for d in turn["diagnostics"]:
            ch = classify(d)
            hit.setdefault(ch, []).append({
                "turn": turn["label"], "severity": d["severity"],
                "code": d["code"], "kind": "diag",
            })
        # Count WorkdirDiff artifacts under #9 — any artifact whose path is NOT
        # in any screenshot message (ScreenshotProbe already accounted for).
        shot_paths = {d["extra"].get("path") for d in turn["diagnostics"]
                       if d.get("code") == "sim.screenshot.captured"}
        for a in turn["artifacts"]:
            if a.get("path") in shot_paths:
                continue  # already counted under #8b
            hit["#9 WorkdirDiff"].append({
                "turn": turn["label"], "severity": "info",
                "code": f"artifact.role={a.get('role')}",
                "kind": "artifact",
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

    # Save full trace as JSON
    out_path = RESULTS_DIR / "agent_dialogue_trace.json"
    out_path.write_text(json.dumps({
        "ui_mode": args.mode,
        "launch_sec": launch_sec,
        "driver_probes": [p.name for p in driver.probes],
        "turns": turns,
    }, indent=2, default=str))
    print(f"\n[trace] {out_path}", flush=True)


if __name__ == "__main__":
    main()
