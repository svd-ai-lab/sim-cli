"""End-to-end solve: Workbench → upload geometry → Mechanical → solve → deformation.

Uses the official PyWorkbench example geometry (two_pipes.agdb) from the
ansys/example-data repository. This is the pymechanical-integration example
adapted for our driver.
"""
import json
import os
import subprocess
import time


def screenshot(name):
    """Take screenshot and bring target window to front."""
    # Try Mechanical first, then Workbench
    ps = f"""
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class W32 {{
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
}}
"@
$targets = @('AnsysWBU', 'AnsysFWW')
foreach ($t in $targets) {{
    $p = Get-Process -Name $t -EA SilentlyContinue | ? {{ $_.MainWindowHandle -ne 0 }} | Select -First 1
    if ($p) {{ [W32]::ShowWindow($p.MainWindowHandle, 3); [W32]::SetForegroundWindow($p.MainWindowHandle); break }}
}}
Start-Sleep -Seconds 2
Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing
$s = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$b = New-Object System.Drawing.Bitmap($s.Width, $s.Height)
$g = [System.Drawing.Graphics]::FromImage($b)
$g.CopyFromScreen($s.Location, [System.Drawing.Point]::Empty, $s.Size)
$b.Save('C:\\Temp\\{name}.png')
$g.Dispose(); $b.Dispose()
"""
    subprocess.run(["powershell", "-Command", ps], capture_output=True, timeout=15)
    print(f"  Screenshot: C:\\Temp\\{name}.png")


def main():
    import ansys.workbench.core as pywb

    print("=" * 60)
    print("END-TO-END SOLVE: Two Pipes Static Structural")
    print("=" * 60)

    # Step 1: Launch Workbench
    print("\nStep 1: Launch Workbench...")
    wb = pywb.launch_workbench(release="241")
    time.sleep(5)
    print("  Launched.")

    # Step 2: Upload geometry from example repo
    print("\nStep 2: Upload geometry (two_pipes.agdb)...")
    try:
        wb.upload_file_from_example_repo(
            "pymechanical-integration/agdb/two_pipes.agdb"
        )
        print("  Uploaded two_pipes.agdb from example repo.")
    except Exception as e:
        print(f"  Upload failed: {e}")
        # Try alternative: download manually
        print("  Trying manual download...")
        from ansys.workbench.core.example_data import ExampleData
        local = ExampleData.download(
            "pymechanical-integration/agdb/two_pipes.agdb",
            os.environ.get("TEMP", "C:/Temp"),
        )
        print(f"  Downloaded to: {local}")
        wb.upload_file(os.path.join(os.environ.get("TEMP", "C:/Temp"), local))
        print(f"  Uploaded to server.")

    # Step 3: Create Static Structural system and attach geometry
    print("\nStep 3: Create system and import geometry...")
    journal = """
SetScriptVersion(Version="24.1")
template1 = GetTemplate(TemplateName="Static Structural", Solver="ANSYS")
system1 = template1.CreateSystem()

# Attach geometry file
geometry1 = system1.GetContainer(ComponentName="Geometry")
geometry1.SetFile(FilePath="two_pipes.agdb")

import json, os, codecs
out = os.path.join(os.environ.get("TEMP", "C:/Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": True, "step": "create-and-import"}))
f.close()
"""
    wb.run_script_string(journal, log_level="warning")
    time.sleep(5)
    result_path = os.path.join(os.environ["TEMP"], "sim_wb_result.json")
    with open(result_path, encoding="utf-8") as f:
        r3 = json.load(f)
    print(f"  Result: {r3}")
    screenshot("solve_step3_geometry")

    # Step 4: Start Mechanical server
    print("\nStep 4: Start Mechanical server...")
    port = wb.start_mechanical_server(system_name="SYS")
    print(f"  Port: {port}")
    time.sleep(10)

    # Step 5: Connect PyMechanical
    print("\nStep 5: Connect PyMechanical...")
    from ansys.mechanical.core import connect_to_mechanical

    mech = connect_to_mechanical(ip="localhost", port=port)
    print(f"  Connected. Version: {mech.version}")
    print(f"  Project dir: {mech.project_directory}")

    # Step 6: Check geometry imported
    print("\nStep 6: Check geometry...")
    geo_count = mech.run_python_script("Model.Geometry.Children.Count")
    print(f"  Geometry children: {geo_count}")

    body_count = mech.run_python_script(
        "len([b for b in Model.Geometry.GetChildren("
        "Ansys.Mechanical.DataModel.Enums.DataModelObjectCategory.Body, True)])"
    )
    print(f"  Body count: {body_count}")
    screenshot("solve_step6_geometry_loaded")

    # Step 7: Generate mesh
    print("\nStep 7: Generate mesh...")
    try:
        mesh_result = mech.run_python_script(
            "Model.Mesh.GenerateMesh()\n"
            "str(Model.Mesh.Nodes.Count)"
        )
        print(f"  Mesh nodes: {mesh_result}")
    except Exception as e:
        print(f"  Mesh error: {str(e)[:150]}")
        # Try with element size
        mesh_result = mech.run_python_script(
            'Model.Mesh.ElementSize = Quantity("5 [mm]")\n'
            "Model.Mesh.GenerateMesh()\n"
            "str(Model.Mesh.Nodes.Count)"
        )
        print(f"  Mesh nodes (retry): {mesh_result}")

    screenshot("solve_step7_meshed")

    # Step 8: Apply boundary conditions and solve
    print("\nStep 8: Apply BCs and solve...")
    bc_result = mech.run_python_script(
        "analysis = Model.Analyses[0]\n"
        "# Add fixed support on first face\n"
        "fix = analysis.AddFixedSupport()\n"
        "# Add pressure on another face\n"
        "pressure = analysis.AddPressure()\n"
        'pressure.Magnitude.Output.SetDiscreteValue(0, Quantity("1 [MPa]"))\n'
        "str(analysis.Children.Count)"
    )
    print(f"  BC children count: {bc_result}")

    # Solve
    print("  Solving...")
    try:
        solve_status = mech.run_python_script(
            "analysis = Model.Analyses[0]\n"
            "analysis.Solve(True)\n"
            "str(analysis.Solution.Status)"
        )
        print(f"  Solve status: {solve_status}")
    except Exception as e:
        print(f"  Solve error: {str(e)[:200]}")

    screenshot("solve_step8_solved")

    # Step 9: Extract results
    print("\nStep 9: Extract deformation results...")
    try:
        deform = mech.run_python_script(
            "solution = Model.Analyses[0].Solution\n"
            "deform = solution.AddTotalDeformation()\n"
            "solution.EvaluateAllResults()\n"
            "str(deform.Maximum)"
        )
        print(f"  Max deformation: {deform}")
        screenshot("solve_step9_results")
    except Exception as e:
        print(f"  Result error: {str(e)[:200]}")

    # Final
    mech.exit()
    print("\n" + "=" * 60)
    print("END-TO-END SOLVE COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
