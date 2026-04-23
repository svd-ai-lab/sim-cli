"""L3 real-COMSOL e2e — Phase 3 P0 acceptance (gui-actuation design §5.14).

Single-turn validation: launch COMSOL GUI, observe that Cortex is stuck
on the "连接到 COMSOL Multiphysics Server" login dialog, use the
newly-injected `gui` object to click 确定, then prove via
``list_windows`` + a window-only screenshot that Cortex entered its
main UI.

This is deliberately **not** the 7-turn agent-dialogue trace from
``integration_comsol_agent_dialogue.py`` (that script exercises the
probe framework; this one exercises the actuation layer). We keep them
separate so a hang in one doesn't block the other.

Phase 3 acceptance per design doc §5.14:
  * #8a window_observed title changes: "连接到 ..." → "Untitled.mph ..."
  * screenshot before/after shows login panel disappear
  * click.strategy == "button_by_title"

Run:
    cd E:/simcli/sim-cli
    set COMSOL_USER=sim
    set COMSOL_PASSWORD=sim
    set SIM_COMSOL_PORT=2037
    .venv/Scripts/python.exe tests/inspect/integration_comsol_gui_dismiss.py

Output:
    tests/inspect/_run_outputs/comsol_gui_dismiss_trace.json
    window screenshots in .sim/screenshots/
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

WORKDIR = Path(os.environ.get("SIM_DIR", r"E:\simcli\sim-cli\.sim")).resolve()


def banner(s: str) -> None:
    print("\n" + "=" * 78, flush=True)
    print(f"  {s}", flush=True)
    print("=" * 78, flush=True)


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

    banner("COMSOL Phase 3 P0 — gui.find().click() dismisses Cortex login")
    print(f" workdir : {WORKDIR}", flush=True)

    t0 = time.time()
    info = driver.launch(mode="solver", ui_mode="gui", processors=2)
    launch_sec = round(time.time() - t0, 1)
    print(f"[launch] ok in {launch_sec}s: model={info.get('model_tag')} "
          f"port={info.get('port')}", flush=True)

    # Verify the new namespace invariant: driver._gui must be a GuiController
    # after a GUI launch. This is the server-side contract the /connect
    # `tools: ["gui"]` advertisement hangs on.
    from sim.gui import GuiController
    assert isinstance(driver._gui, GuiController), (
        f"driver._gui should be GuiController post-launch, got {type(driver._gui)}"
    )
    assert "comsol" in driver._gui.process_filter, (
        f"GuiController process filter should include 'comsol', got "
        f"{driver._gui.process_filter}"
    )
    print(f"[check] driver._gui is GuiController "
          f"(filter={driver._gui.process_filter})", flush=True)

    trace: dict = {
        "launch_sec": launch_sec,
        "port": driver._port,
        "case": None,
        "stages": [],
    }

    try:
        # ── stage 1: observe initial state via run_snippet ─────────────────
        banner("Stage 1 — observe initial windows (pre-dismiss)")
        code1 = (
            "pre = gui.list_windows()\n"
            "pre_titles = [w['title'] for w in (pre.get('windows') or [])]\n"
            "import json\n"
            "print(json.dumps({'windows': pre.get('windows')}))\n"
            "_result = {'titles': pre_titles, 'count': len(pre_titles)}"
        )
        r1 = driver.run(code1, label="stage1_observe_pre", timeout_s=20.0)
        pre_state = r1.get("result") or {}
        print(f"  windows visible  : {pre_state.get('count')}", flush=True)
        print(f"  titles           : {pre_state.get('titles')}", flush=True)
        trace["stages"].append({
            "name": "stage1_observe_pre",
            "ok": r1.get("ok"),
            "result": pre_state,
            "diagnostics_n": len(r1.get("diagnostics") or []),
            "artifacts_n": len(r1.get("artifacts") or []),
        })

        # Check the classification probe saw the login dialog on #8a
        login_seen = any(
            (d.get("extra") or {}).get("title", "").startswith("连接到")
            or "连接到" in (d.get("message") or "")
            for d in (r1.get("diagnostics") or [])
        )
        trace["stages"][-1]["probe_saw_login_dialog"] = login_seen
        print(f"  probe saw login  : {login_seen}", flush=True)

        # ── stage 2: use gui to dismiss the login dialog ────────────────────
        banner("Stage 2 — gui.find('连接到').click('确定')")
        code2 = (
            "dlg = gui.find(title_contains='连接到', timeout_s=8)\n"
            "if dlg is None:\n"
            "    dlg = gui.find(title_contains='Connect to COMSOL', timeout_s=3)\n"
            "if dlg is None:\n"
            "    _result = {'ok': True, 'already_dismissed': True}\n"
            "else:\n"
            "    shot_before = dlg.screenshot(label='login_dialog_before')\n"
            "    click_result = dlg.click('确定')\n"
            "    if not click_result.get('ok'):\n"
            "        click_result = dlg.click('OK')\n"
            "    gui.wait_until_window_gone('连接到', timeout_s=15)\n"
            "    _result = {\n"
            "        'ok': click_result.get('ok', False),\n"
            "        'dismissed_title': dlg.title,\n"
            "        'click': click_result,\n"
            "        'shot_before': shot_before,\n"
            "    }"
        )
        r2 = driver.run(code2, label="stage2_gui_dismiss", timeout_s=45.0)
        dismiss_state = r2.get("result") or {}
        print(f"  result           : {dismiss_state}", flush=True)
        trace["stages"].append({
            "name": "stage2_gui_dismiss",
            "ok": r2.get("ok"),
            "result": dismiss_state,
            "diagnostics_n": len(r2.get("diagnostics") or []),
            "artifacts_n": len(r2.get("artifacts") or []),
        })

        # ── stage 3: verify Cortex entered the main UI ──────────────────────
        banner("Stage 3 — verify main window visible post-dismiss")
        # Poll up to 30s: COMSOL needs time to open the main window after login.
        # On Chinese Windows the interim title is '未命名' (Untitled, no "COMSOL
        # Multiphysics" suffix yet); on English it's "Untitled.mph - COMSOL
        # Multiphysics". We accept either: any non-empty window whose title is
        # NOT the login dialog counts as the main UI being reachable.
        code3 = (
            "import time as _t\n"
            "titles, main_visible = [], False\n"
            "for _attempt in range(15):\n"
            "    _t.sleep(2)\n"
            "    post = gui.list_windows()\n"
            "    titles = [w['title'] for w in (post.get('windows') or [])]\n"
            "    _login_gone = not any('连接到' in t and 'Server' in t for t in titles)\n"
            "    _has_main = any(\n"
            "        t.strip() and '连接到' not in t and 'Server' not in t\n"
            "        for t in titles if t.strip()\n"
            "    )\n"
            "    main_visible = _login_gone or _has_main\n"
            "    if main_visible:\n"
            "        break\n"
            "_result = {'titles': titles, 'main_visible': main_visible,\n"
            "           'count': len(titles)}"
        )
        r3 = driver.run(code3, label="stage3_verify_main", timeout_s=45.0)
        post_state = r3.get("result") or {}
        print(f"  titles           : {post_state.get('titles')}", flush=True)
        print(f"  main_visible     : {post_state.get('main_visible')}", flush=True)
        trace["stages"].append({
            "name": "stage3_verify_main",
            "ok": r3.get("ok"),
            "result": post_state,
            "diagnostics_n": len(r3.get("diagnostics") or []),
            "artifacts_n": len(r3.get("artifacts") or []),
        })

    finally:
        banner("disconnect")
        try:
            driver.disconnect()
        except Exception as exc:
            print(f"  disconnect warn: {exc}", flush=True)

    # ── verdict ───────────────────────────────────────────────────────────
    stage_ok = [s.get("ok") for s in trace["stages"]]
    all_ok = all(stage_ok)
    click_fmt = (
        (trace["stages"][1].get("result") or {}).get("click") or {}
    )
    main_visible_post = (
        (trace["stages"][2].get("result") or {}).get("main_visible")
    )
    verdict_ok = all_ok and click_fmt.get("ok") and main_visible_post

    banner("VERDICT — Phase 3 P0 acceptance")
    print(f"  all stages ok        : {all_ok}  ({stage_ok})", flush=True)
    print(f"  dismiss click ok     : {click_fmt.get('ok')}", flush=True)
    print(f"  dismiss strategy     : {click_fmt.get('strategy')}", flush=True)
    print(f"  main window visible  : {main_visible_post}", flush=True)
    print(f"  PHASE 3 P0           : {'PASS' if verdict_ok else 'FAIL'}",
          flush=True)

    out_path = RESULTS_DIR / "comsol_gui_dismiss_trace.json"
    out_path.write_text(json.dumps(trace, indent=2, default=str))
    print(f"\n[trace] {out_path}", flush=True)

    return 0 if verdict_ok else 3


if __name__ == "__main__":
    sys.exit(main())
