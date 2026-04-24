"""Real CFX e2e for probe wiring — launches cfx5post -line on VMFL015.

Purpose: verify that CfxDriver.run() actually populates diagnostics +
artifacts on a live cfx5post session, and (critically) capture the real
stderr/stdout text on a forced-error command so we can audit the
_CFX_STDOUT_RULES patterns against reality rather than guesses.

Usage::

    uv run python tests/inspect/e2e_cfx_probe_wiring.py

Requires:
  * CFX 24.1 installed (driver.connect() status == "ok")
  * VMFL015 .res at the hard-coded RES_FILE path
"""
from __future__ import annotations

import json
from pathlib import Path
from pprint import pformat

from sim.drivers.cfx import CfxDriver

RES_FILE = Path(
    r"E:\CFX_tutorial\test_case_to_rrh\test_case_to_rrh\VMFL015_CFX"
    r"\input\015_001.res"
)


def _summarize(label: str, r: dict) -> None:
    print(f"\n── {label} " + "─" * max(0, 70 - len(label)))
    print(f"  ok={r.get('ok')}  error={r.get('error')!r}")
    stdout = r.get("stdout", "") or ""
    stderr = r.get("stderr", "") or ""
    if stdout:
        print(f"  stdout ({len(stdout)} chars), first 6 lines:")
        for line in stdout.splitlines()[:6]:
            print(f"    | {line}")
    if stderr:
        print(f"  stderr ({len(stderr)} chars), first 6 lines:")
        for line in stderr.splitlines()[:6]:
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
    drv = CfxDriver()
    ci = drv.connect()
    print(f"CFX: {ci.status} {ci.version}")
    if ci.status != "ok":
        print("CFX not available — abort")
        return 2

    print(f"\nLaunching cfx5post on {RES_FILE.name} (skip_solve=True) ...")
    info = drv.launch(res_file=str(RES_FILE), skip_solve=True)
    if not info.get("ok"):
        print(f"launch failed: {info}")
        return 3
    print(f"  session_id={info.get('session_id')}  mode={info.get('mode')}")

    all_results: list[dict] = []

    # ── case A: a simple session command (should succeed) ──
    rA = drv.run("s", label="list_objects")
    _summarize("A: session 's' command", rA)
    all_results.append(rA)

    # ── case B: evaluate() that is expected to succeed ──
    rB = drv.run("evaluate(area()@inlet)", label="area_inlet")
    _summarize("B: evaluate(area()@inlet)", rB)
    all_results.append(rB)

    # ── case C: a deliberately invalid Perl command ──
    # The '!' prefix routes to send_command as Perl; nonsense syntax will
    # force cfx5post to emit whatever error format it actually uses —
    # that text is what _CFX_STDOUT_RULES must match against.
    rC = drv.run("!this_function_does_not_exist_xyz()", label="bad_perl")
    _summarize("C: bad Perl (intentional error)", rC)
    all_results.append(rC)

    # ── case D: evaluate on a nonexistent location ──
    rD = drv.run("evaluate(area()@NO_SUCH_LOCATION)", label="bad_location")
    _summarize("D: evaluate on missing location", rD)
    all_results.append(rD)

    drv.disconnect()

    # ── assertions ──
    errors: list[str] = []
    for label, r in zip("ABCD", all_results):
        if not isinstance(r.get("diagnostics"), list):
            errors.append(f"{label}: diagnostics is not a list")
        if not isinstance(r.get("artifacts"), list):
            errors.append(f"{label}: artifacts is not a list")
        # Must always have at least ProcessMeta's exit_{zero,nonzero}
        codes = [d.get("code") for d in (r.get("diagnostics") or [])]
        if not any(c in ("sim.process.exit_zero", "sim.process.exit_nonzero")
                   for c in codes):
            errors.append(f"{label}: no exit_zero/exit_nonzero diag; codes={codes}")
        # JSON round-trip
        try:
            json.dumps(r.get("diagnostics", []))
            json.dumps(r.get("artifacts", []))
        except Exception as e:
            errors.append(f"{label}: diagnostics not JSON-serializable: {e}")

    trace = Path(__file__).parent / "_run_outputs" / "cfx_probe_wiring_e2e.json"
    trace.parent.mkdir(parents=True, exist_ok=True)
    trace.write_text(json.dumps(all_results, indent=2, default=str),
                     encoding="utf-8")
    print(f"\n[trace] {trace}")

    if errors:
        print("\nFAIL:\n" + "\n".join(f"  - {e}" for e in errors))
        return 1
    print("\nVERDICT — CFX probe-wiring e2e: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
