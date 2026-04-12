"""Update Geometry cell to transition from ? to green checkmark.

This test proves visually that a Workbench cell can be updated to the
"successful" state. We do NOT solve anything — just attach geometry
and trigger Refresh/Update on the Geometry cell.

Expected outcome:
- Before: Geometry cell shows ?
- After:  Geometry cell shows green [OK] (and Model cell may also update)
"""
import os
import subprocess
import time

import ansys.workbench.core as pywb

TEMP = os.environ["TEMP"]


def activate_and_screenshot(name):
    """Bring Workbench to front and capture."""
    ps = f"""
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class W {{
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
    [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
}}
"@
$shell = New-Object -ComObject WScript.Shell
$wb = Get-Process -Name 'AnsysFWW' -EA SilentlyContinue | ? {{ $_.MainWindowHandle -ne 0 }} | Select -First 1
if ($wb) {{
    $shell.AppActivate($wb.Id) | Out-Null
    Start-Sleep -Milliseconds 500
    [W]::ShowWindow($wb.MainWindowHandle, 3)
    [W]::BringWindowToTop($wb.MainWindowHandle)
    Start-Sleep -Seconds 2
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $s = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    $b = New-Object System.Drawing.Bitmap($s.Width, $s.Height)
    $g = [System.Drawing.Graphics]::FromImage($b)
    $g.CopyFromScreen($s.Location, [System.Drawing.Point]::Empty, $s.Size)
    $b.Save('C:\\Temp\\{name}.png')
    $g.Dispose()
    $b.Dispose()

    # Also crop to system schematic
    $src = [System.Drawing.Image]::FromFile('C:\\Temp\\{name}.png')
    $crop = New-Object System.Drawing.Rectangle(225, 25, 300, 350)
    $dst = New-Object System.Drawing.Bitmap(600, 700)
    $g2 = [System.Drawing.Graphics]::FromImage($dst)
    $g2.DrawImage($src, (New-Object System.Drawing.Rectangle(0, 0, 600, 700)), $crop, [System.Drawing.GraphicsUnit]::Pixel)
    $dst.Save('C:\\Temp\\{name}_crop.png')
    $src.Dispose(); $g2.Dispose(); $dst.Dispose()
}}
"""
    subprocess.run(["powershell", "-Command", ps], capture_output=True, timeout=30)
    print(f"  [screenshot] C:\\Temp\\{name}.png and {name}_crop.png")


def main():
    print("=" * 70)
    print("GEOMETRY CELL UPDATE — Transition from ? to [OK]")
    print("=" * 70)

    # Step 1: Launch
    print("\n[1] Launch Workbench")
    wb = pywb.launch_workbench(release="241")
    time.sleep(8)

    # Step 2: Create fresh Static Structural system
    print("\n[2] Create Static Structural system")
    wb.run_script_string("""
SetScriptVersion(Version="24.1")
t = GetTemplate(TemplateName="Static Structural", Solver="ANSYS")
s = t.CreateSystem()
""", log_level="warning")
    time.sleep(5)

    # Screenshot BEFORE update — should show Geometry as ?
    print("\n[3] Capture BEFORE state")
    activate_and_screenshot("cell_before")
    time.sleep(2)

    # Step 4: Upload real geometry file
    print("\n[4] Upload two_pipes.agdb")
    geo_path = os.path.join(TEMP, "two_pipes.agdb")
    if not os.path.exists(geo_path) or os.path.getsize(geo_path) < 100_000:
        import requests
        url = "https://github.com/ansys/example-data/raw/master/pyworkbench/pymechanical-integration/agdb/two_pipes.agdb"
        r = requests.get(url, allow_redirects=True, timeout=60)
        with open(geo_path, "wb") as f:
            f.write(r.content)
    wb.upload_file(geo_path)
    print(f"  Uploaded: {geo_path}")

    # Step 5: Attach geometry with absolute path + Refresh
    print("\n[5] SetFile with absolute path + Refresh Geometry cell")
    wb.run_script_string("""
import os
s = GetAllSystems()[0]
geo = s.GetContainer(ComponentName="Geometry")
geo_path = os.path.join(os.environ.get("TEMP", "C:/Temp"), "two_pipes.agdb")
geo.SetFile(FilePath=geo_path)
""", log_level="warning")
    time.sleep(3)

    print("\n[6] Capture AFTER SetFile (should still be in transition)")
    activate_and_screenshot("cell_after_setfile")

    # Step 6: Trigger Geometry cell Update (this is the key — actually
    # refreshes/imports the geometry, making the cell show [OK])
    print("\n[7] Call geometry.Refresh() to commit the file")
    wb.run_script_string("""
s = GetAllSystems()[0]
geo = s.GetContainer(ComponentName="Geometry")
geo.Refresh()
""", log_level="warning")

    # Wait for geometry import to complete (SpaceClaim/DM processing)
    print("  Waiting up to 90s for geometry import...")
    for i in range(9):
        time.sleep(10)
        print(f"  Waited {(i+1)*10}s")

    # Screenshot AFTER update — should show Geometry as [OK]
    print("\n[8] Capture FINAL state (should have [OK] on Geometry)")
    activate_and_screenshot("cell_after_refresh")

    # Also try triggering full Update on the system
    print("\n[9] Call system.Update() to propagate")
    try:
        wb.run_script_string("""
s = GetAllSystems()[0]
s.Update()
""", log_level="warning")
        print("  Update called")
    except Exception as e:
        print(f"  Update error: {str(e)[:100]}")

    time.sleep(15)
    activate_and_screenshot("cell_after_update")

    print("\n" + "=" * 70)
    print("DONE")
    print("Screenshots:")
    print("  C:\\Temp\\cell_before.png / cell_before_crop.png")
    print("  C:\\Temp\\cell_after_setfile.png / cell_after_setfile_crop.png")
    print("  C:\\Temp\\cell_after_refresh.png / cell_after_refresh_crop.png")
    print("  C:\\Temp\\cell_after_update.png / cell_after_update_crop.png")
    print("=" * 70)


if __name__ == "__main__":
    main()
