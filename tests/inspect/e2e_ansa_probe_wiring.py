"""Real ANSA e2e for probe wiring — launches ANSA in no_gui listener mode.

Purpose: verify that AnsaDriver.run() actually populates diagnostics +
artifacts on a live ANSA IAP session, and capture the real stderr/stdout
on a forced-error snippet so we can audit _ANSA_STDOUT_RULES against
reality.

Usage::

    uv run python tests/inspect/e2e_ansa_probe_wiring.py

Requires ANSA installed (driver.connect() status == "ok").
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from sim.drivers.ansa.driver import AnsaDriver


def _summarize(label: str, r: dict) -> None:
    print(f"\n── {label} " + "─" * max(0, 70 - len(label)))
    print(f"  ok={r.get('ok')}  error={r.get('error')!r}")
    stdout = r.get("stdout", "") or ""
    stderr = r.get("stderr", "") or ""
    if stdout:
        print(f"  stdout ({len(stdout)} chars), first 8 lines:")
        for line in stdout.splitlines()[:8]:
            print(f"    | {line}")
    if stderr:
        print(f"  stderr ({len(stderr)} chars), first 8 lines:")
        for line in stderr.splitlines()[:8]:
            print(f"    | {line}")
    diags = r.get("diagnostics", [])
    print(f"  diagnostics ({len(diags)}):")
    for d in diags:
        print(f"    - [{d.get('severity', '?'):5s}] {d.get('code')}  "
              f"source={d.get('source')!r}  msg={d.get('message', '')[:80]!r}")
    arts = r.get("artifacts", [])
    if arts:
        print(f"  artifacts ({len(arts)}):")
        for a in arts:
            print(f"    - {a.get('kind')}  path={a.get('path')}")


def main() -> int:
    drv = AnsaDriver()
    ci = drv.connect()
    print(f"ANSA: {ci.status} {ci.version}")
    if ci.status != "ok":
        print("ANSA not available — abort")
        return 2

    t0 = time.time()
    print("\nLaunching ANSA in gui listener mode ...")
    # nogui listener aborts the IAP handshake on this host (pre-existing
    # ANSA 25 issue unrelated to probe wiring). Use gui mode which has a
    # stable listener.
    info = drv.launch(ui_mode="gui")
    launch_sec = time.time() - t0
    if not info.get("ok"):
        print(f"launch failed: {info}")
        return 3
    print(f"  session_id={info.get('session_id')}  "
          f"port={info.get('port')}  launch={launch_sec:.1f}s")

    all_results: list[dict] = []

    # ── case A: a simple print from inside main() (success path) ──
    codeA = (
        "def main():\n"
        "    print('hello from ansa')\n"
        "    return {'ok': 'true', 'value': '42'}\n"
    )
    rA = drv.run(codeA, label="simple_print")
    _summarize("A: simple print + return dict", rA)
    all_results.append(rA)

    # ── case B: raise an exception inside main() (failure path) ──
    codeB = (
        "def main():\n"
        "    raise ValueError('deliberate test failure')\n"
    )
    rB = drv.run(codeB, label="raises_value_error")
    _summarize("B: raise ValueError inside main()", rB)
    all_results.append(rB)

    # ── case C: import ansa and query simple state ──
    codeC = (
        "def main():\n"
        "    from ansa import base\n"
        "    deck = base.CurrentDeck()\n"
        "    print(f'deck={deck}')\n"
        "    return {'deck': str(deck)}\n"
    )
    rC = drv.run(codeC, label="ansa_base_import")
    _summarize("C: import ansa.base, query CurrentDeck", rC)
    all_results.append(rC)

    drv.disconnect()

    # ── assertions ──
    errors: list[str] = []
    for label, r in zip("ABC", all_results):
        if not isinstance(r.get("diagnostics"), list):
            errors.append(f"{label}: diagnostics not a list")
        if not isinstance(r.get("artifacts"), list):
            errors.append(f"{label}: artifacts not a list")
        codes = [d.get("code") for d in (r.get("diagnostics") or [])]
        if not any(c in ("sim.process.exit_zero", "sim.process.exit_nonzero")
                   for c in codes):
            errors.append(f"{label}: no exit_zero/exit_nonzero; codes={codes}")
        try:
            json.dumps(r.get("diagnostics", []))
            json.dumps(r.get("artifacts", []))
        except Exception as e:
            errors.append(f"{label}: diagnostics not JSON-serializable: {e}")

    trace = Path(__file__).parent / "_run_outputs" / "ansa_probe_wiring_e2e.json"
    trace.parent.mkdir(parents=True, exist_ok=True)
    trace.write_text(json.dumps(all_results, indent=2, default=str),
                     encoding="utf-8")
    print(f"\n[trace] {trace}")

    if errors:
        print("\nFAIL:\n" + "\n".join(f"  - {e}" for e in errors))
        return 1
    print("\nVERDICT — ANSA probe-wiring e2e: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
