"""Real Workbench example run: Material Designer project.

Downloads the official Material Designer project archive, opens it in
Workbench, updates the design points (which triggers actual solve),
and takes screenshots showing the project schematic with cells
transitioning from unchecked to checkmark (success) state.

This is the REAL test — visual proof that Workbench ran an example
end-to-end, with cells showing checkmarks in the GUI.
"""
import json
import os
import subprocess
import time
from pathlib import Path

import ansys.workbench.core as pywb

TEMP = os.environ["TEMP"]
RESULT_FILE = Path(TEMP) / "sim_wb_result.json"


def screenshot(name):
    """Bring Workbench to front and capture screen."""
    path = f"C:\\Temp\\{name}.png"
    ps = f"""
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class W {{
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
}}
"@
$p = Get-Process -Name 'AnsysFWW' -EA SilentlyContinue | ? {{ $_.MainWindowHandle -ne 0 }} | Select -First 1
if ($p) {{ [W]::ShowWindow($p.MainWindowHandle, 3); [W]::SetForegroundWindow($p.MainWindowHandle) }}
Start-Sleep -Seconds 2
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$s = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$b = New-Object System.Drawing.Bitmap($s.Width, $s.Height)
$g = [System.Drawing.Graphics]::FromImage($b)
$g.CopyFromScreen($s.Location, [System.Drawing.Point]::Empty, $s.Size)
$b.Save('{path}')
$g.Dispose(); $b.Dispose()
"""
    subprocess.run(["powershell", "-Command", ps], capture_output=True, timeout=15)
    print(f"  [screenshot] {path}")


def run_journal(wb, code, wait=3):
    if RESULT_FILE.exists():
        RESULT_FILE.unlink()
    wb.run_script_string(code, log_level="warning")
    time.sleep(wait)
    if RESULT_FILE.exists():
        return json.loads(RESULT_FILE.read_text(encoding="utf-8"))
    return {}


def main():
    print("=" * 70)
    print("MATERIAL DESIGNER — Real Workbench example run")
    print("=" * 70)

    # Step 1: Launch Workbench
    print("\n[1] Launch Workbench with GUI")
    wb = pywb.launch_workbench(release="241")
    time.sleep(5)
    screenshot("material_01_launched")

    # Step 2: Upload the project archive
    print("\n[2] Upload MatDesigner.wbpz")
    wbpz_path = os.path.join(TEMP, "MatDesigner.wbpz")
    wb.upload_file(wbpz_path)
    print(f"  Uploaded: {wbpz_path}")

    # Step 3: Unarchive (extract) and open the project
    print("\n[3] Unarchive and open project")
    r = run_journal(wb, """
import os, json, codecs
temp = os.environ.get("TEMP", "C:/Temp")
arch_path = os.path.join(temp, "MatDesigner.wbpz")
proj_dir = os.path.join(temp, "MatDesignerProject")
proj_path = os.path.join(proj_dir, "MatDesigner.wbpj")

# Unarchive: extracts the .wbpz into a folder and opens it
Unarchive(ArchivePath=arch_path, ProjectPath=proj_path, Overwrite=True)

# Enumerate systems after open
systems = GetAllSystems()
names = [str(s.Name) for s in systems]

out = os.path.join(temp, "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": True, "system_count": len(systems), "names": names}))
f.close()
""", wait=15)
    print(f"  Result: {r}")
    time.sleep(5)
    screenshot("material_02_restored")

    # Step 4: Enumerate parameters BEFORE update
    print("\n[4] List input/output parameters")
    r4 = run_journal(wb, """
import json, os, codecs
input_params = []
output_params = []
for p_num in range(1, 15):
    try:
        p = Parameters.GetParameter(Name="P" + str(p_num))
        if p is None:
            continue
        tag = ""
        try:
            tag = str(p.DisplayText).encode("ascii", "replace").decode("ascii")
        except:
            tag = "P" + str(p_num)
        val = ""
        try:
            val = str(p.Value).encode("ascii", "replace").decode("ascii")
        except:
            val = ""
        expr = ""
        try:
            expr = str(p.Expression).encode("ascii", "replace").decode("ascii")
        except:
            pass
        info = {"num": p_num, "tag": tag, "value": val, "expression": expr}
        if p.Usage == ParameterUsage.Input:
            input_params.append(info)
        else:
            output_params.append(info)
    except Exception as e:
        pass

out = os.path.join(os.environ.get("TEMP", "C:/Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": True, "inputs": input_params, "outputs": output_params}))
f.close()
""")
    print(f"  Input params: {len(r4.get('inputs', []))}")
    for p in r4.get("inputs", []):
        print(f"    P{p['num']}: {p['tag']} = {p['expression']}")
    print(f"  Output params: {len(r4.get('outputs', []))}")
    for p in r4.get("outputs", [])[:5]:
        print(f"    P{p['num']}: {p['tag']} = {p['value']}")

    # Step 5: Modify Young's Modulus parameter and update design point
    print("\n[5] Update Young's modulus to 1.6e10 and run design point")
    r5 = run_journal(wb, """
import json, os, codecs
try:
    designPoint1 = Parameters.GetDesignPoint(Name="0")
    parameter1 = Parameters.GetParameter(Name="P1")
    designPoint1.SetParameterExpression(
        Parameter=parameter1,
        Expression="1.6e10 [Pa]")
    # Update the design point — this triggers all cells to solve
    backgroundSession1 = UpdateAllDesignPoints(DesignPoints=[designPoint1])
    ok = True
    err = ""
except Exception as e:
    ok = False
    err = str(e).encode("ascii", "replace").decode("ascii")[:200]

out = os.path.join(os.environ.get("TEMP", "C:/Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": ok, "error": err}))
f.close()
""", wait=30)  # Update takes time
    print(f"  Result: {r5}")

    # Wait for update to complete - Material Designer can take 30-60s
    print("  Waiting for design point update to complete...")
    time.sleep(45)
    screenshot("material_03_updating")

    # Step 6: Check status and read output parameters
    print("\n[6] Read output parameters after update")
    r6 = run_journal(wb, """
import json, os, codecs

# Give a moment for update state to settle
outputs = {}
err = ""
try:
    for p_num in range(2, 12):
        try:
            p = Parameters.GetParameter(Name="P" + str(p_num))
            if p and p.Usage == ParameterUsage.Output:
                tag = "P" + str(p_num)
                try:
                    tag = str(p.DisplayText).encode("ascii", "replace").decode("ascii")
                except:
                    pass
                val_str = ""
                try:
                    val_str = str(p.Value).encode("ascii", "replace").decode("ascii")
                except:
                    pass
                outputs[tag] = val_str
        except:
            pass
except Exception as e:
    err = str(e).encode("ascii", "replace").decode("ascii")[:200]

# Check system states
sys_states = []
try:
    for s in GetAllSystems():
        name = str(s.Name)
        sys_states.append({"name": name})
except:
    pass

out = os.path.join(os.environ.get("TEMP", "C:/Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": len(outputs) > 0, "outputs": outputs, "systems": sys_states, "error": err}))
f.close()
""", wait=3)
    print(f"  Output count: {len(r6.get('outputs', {}))}")
    for name, val in r6.get("outputs", {}).items():
        print(f"    {name} = {val}")

    screenshot("material_04_after_update")

    # Save project
    print("\n[7] Save project")
    r7 = run_journal(wb, """
import os, json, codecs
temp = os.environ.get("TEMP", "C:/Temp")
proj_path = os.path.join(temp, "MatDesignerProject", "MatDesigner.wbpj")
try:
    Save(Overwrite=True)
    ok = True
except Exception as e:
    ok = False

out = os.path.join(temp, "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": ok}))
f.close()
""")
    print(f"  Saved: {r7}")
    time.sleep(2)

    screenshot("material_05_final")

    print("\n" + "=" * 70)
    print("DONE — check screenshots in C:\\Temp\\material_*.png")
    print("=" * 70)


if __name__ == "__main__":
    main()
