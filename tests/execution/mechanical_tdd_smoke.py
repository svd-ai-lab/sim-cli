"""TDD run — Mechanical driver + snippets 01/02/06 on real Ansys 24.1.

What this proves:
    • MechanicalDriver.launch opens Mechanical with a visible GUI
    • run_python_script returns results for snippets 01, 02, 06
    • The structured JSON result is parseable by parse_output
    • screenshot captures the Mechanical window

Screenshots land in C:/Temp/mech_*.png.

We do not solve here — solving needs a .mechdb with BCs, that belongs
to a separate end-to-end workflow test. This is the smoke test.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# ensure we can import sim
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from sim.drivers.mechanical import MechanicalDriver

SNIPPETS_DIR = Path(
    "E:/simcli/sim-skills/mechanical/base/snippets"
)

SCREENSHOT_DIR = Path("C:/Temp")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


def screenshot(name: str) -> None:
    """Bring Mechanical to front and grab the desktop."""
    path = SCREENSHOT_DIR / f"mech_{name}.png"
    ps = f"""
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class W {{
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
}}
"@
$shell = New-Object -ComObject WScript.Shell
$p = Get-Process -Name 'AnsysWBU','Ansys.Mechanical.WorkBench' -EA SilentlyContinue |
     ? {{ $_.MainWindowHandle -ne 0 }} | Select -First 1
if ($p) {{
    $shell.AppActivate($p.Id) | Out-Null
    Start-Sleep -Milliseconds 500
    [W]::ShowWindow($p.MainWindowHandle, 3)
    Start-Sleep -Seconds 2
}}
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$s = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$b = New-Object System.Drawing.Bitmap($s.Width, $s.Height)
$g = [System.Drawing.Graphics]::FromImage($b)
$g.CopyFromScreen($s.Location, [System.Drawing.Point]::Empty, $s.Size)
$b.Save('{path}')
$g.Dispose(); $b.Dispose()
"""
    subprocess.run(
        ["powershell", "-Command", ps], capture_output=True, timeout=30,
    )
    print(f"  [screenshot] {path}")


def run_snippet(driver: MechanicalDriver, name: str) -> dict:
    p = SNIPPETS_DIR / name
    code = p.read_text(encoding="utf-8")
    print(f"\n[exec] {name}")
    out = driver.run(code, label=name)
    print(f"  ok={out['ok']}  elapsed={out['elapsed_s']}s")
    if out["error"]:
        print(f"  error: {out['error'][:200]}")
    if out["stdout"]:
        print(f"  stdout (last 200): {out['stdout'][-200:]}")
    print(f"  parsed: {out['result']}")
    return out


def main() -> int:
    print("=" * 70)
    print("MECHANICAL TDD — snippets 01, 02, 06 against real Ansys 24.1")
    print("=" * 70)

    d = MechanicalDriver()
    installs = d.detect_installed()
    print(f"\n[detect] found {len(installs)} install(s)")
    for i in installs:
        print(f"  {i.version} at {i.path} via {i.source}")
    if not installs:
        print("ABORT: no Mechanical install")
        return 2

    print(f"\n[connect] {d.connect()}")

    # Launch Mechanical with GUI
    print("\n[launch] launching Mechanical with GUI (batch=False)...")
    t0 = time.time()
    info = d.launch(ui_mode="gui")
    print(f"  launched in {time.time()-t0:.1f}s: {info}")

    # Screenshot the initial state
    time.sleep(3)
    screenshot("01_launched")

    # Snippet 01 — smoke
    s1 = run_snippet(d, "01_smoke.py")
    assert s1["ok"], "snippet 01 failed"
    assert s1["result"] and s1["result"]["ok"], "snippet 01 result failure"
    assert s1["result"]["has_ExtAPI"] is True

    # Snippet 02 — list project tree
    s2 = run_snippet(d, "02_list_project_tree.py")
    assert s2["ok"], "snippet 02 failed"

    # Screenshot after state queries (still a blank project)
    screenshot("02_after_smoke")

    # Snippet 06 — observation coupling check
    s6 = run_snippet(d, "06_observation_check.py")
    assert s6["ok"], "snippet 06 failed"
    assert s6["result"] and s6["result"]["ok"]

    # Session summary
    summary = d.query("session.summary")
    print(f"\n[query] session.summary: {summary}")
    assert summary["connected"]
    assert summary["backend"] == "pymechanical"
    assert summary["run_count"] == 3

    # Try a product_info query (round-trip)
    try:
        pi = d.query("mechanical.product_info")
        print(f"[query] product_info: {str(pi)[:200]}")
    except Exception as e:
        print(f"[query] product_info failed (non-fatal): {e}")

    # Take the final screenshot
    screenshot("03_final")

    print("\n[disconnect] closing Mechanical...")
    d.disconnect()
    print("  disconnected")

    # Build summary JSON for the test report
    summary_file = SCREENSHOT_DIR / "mech_tdd_summary.json"
    summary_file.write_text(json.dumps({
        "ok": True,
        "install": installs[0].to_dict(),
        "launch": info,
        "snippets": {
            "01_smoke": s1["result"],
            "02_list_project_tree": s2["result"],
            "06_observation_check": s6["result"],
        },
    }, indent=2, default=str), encoding="utf-8")
    print(f"\n[summary] {summary_file}")

    print("\n" + "=" * 70)
    print("DONE — all assertions passed")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
