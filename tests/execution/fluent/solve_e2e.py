"""Full E2E: WB → upload geometry → import → mesh → solve → deformation."""
import json
import os
import subprocess
import time

import ansys.workbench.core as pywb


TEMP = os.environ.get("TEMP", "C:/Temp")
RESULT_FILE = os.path.join(TEMP, "sim_wb_result.json")


def shot(name):
    path = os.path.join("C:/Temp", f"{name}.png")
    subprocess.run([
        "powershell", "-Command",
        "Add-Type -AssemblyName System.Windows.Forms;"
        "Add-Type -AssemblyName System.Drawing;"
        "$s=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds;"
        "$b=New-Object System.Drawing.Bitmap($s.Width,$s.Height);"
        "$g=[System.Drawing.Graphics]::FromImage($b);"
        "$g.CopyFromScreen($s.Location,[System.Drawing.Point]::Empty,$s.Size);"
        f"$b.Save('{path}');"
        "$g.Dispose();$b.Dispose()"
    ], capture_output=True, timeout=15)
    print(f"  [screenshot] {path}")


def read_result():
    if os.path.exists(RESULT_FILE):
        with open(RESULT_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def main():
    print("=" * 60)
    print("E2E: Two Pipes Static Structural Analysis")
    print("=" * 60)

    # 1. Launch
    print("\n[1] Launch Workbench")
    wb = pywb.launch_workbench(release="241")
    time.sleep(5)
    print("  OK")

    # 2. Upload geometry
    print("\n[2] Upload geometry (two_pipes.agdb)")
    wb.upload_file_from_example_repo(
        "pymechanical-integration/agdb/two_pipes.agdb"
    )
    print("  OK")

    # 3. Create system + import geometry + Update
    print("\n[3] Create system + import + update")
    wb.run_script_string(
        'SetScriptVersion(Version="24.1")\n'
        'template1 = GetTemplate(TemplateName="Static Structural", Solver="ANSYS")\n'
        "system1 = template1.CreateSystem()\n"
        'geometry1 = system1.GetContainer(ComponentName="Geometry")\n'
        'geometry1.SetFile(FilePath="two_pipes.agdb")\n'
        "system1.Update()\n"
        "import json, os, codecs\n"
        'out = os.path.join(os.environ.get("TEMP","C:/Temp"), "sim_wb_result.json")\n'
        'f = codecs.open(out, "w", "utf-8")\n'
        'f.write(json.dumps({"ok": True, "step": "updated"}))\n'
        "f.close()\n",
        log_level="warning",
    )
    time.sleep(10)
    print(f"  Result: {read_result()}")
    shot("e2e_3_updated")

    # 4. Start Mechanical server
    print("\n[4] Start Mechanical server")
    port = wb.start_mechanical_server(system_name="SYS")
    print(f"  Port: {port}")
    time.sleep(15)

    # 5. Connect PyMechanical
    print("\n[5] Connect PyMechanical")
    from ansys.mechanical.core import connect_to_mechanical
    mech = connect_to_mechanical(ip="localhost", port=port)
    print(f"  Version: {mech.version}")

    # 6. Check geometry
    print("\n[6] Check geometry loaded")
    geo = mech.run_python_script("Model.Geometry.Children.Count")
    print(f"  Geometry children: {geo}")

    if int(geo) > 0:
        bodies = mech.run_python_script(
            "len([b for b in Model.Geometry.GetChildren("
            "Ansys.Mechanical.DataModel.Enums.DataModelObjectCategory.Body, True)])"
        )
        print(f"  Bodies: {bodies}")
    else:
        print("  WARNING: No geometry loaded! Update may not have completed.")

    # 7. Mesh
    print("\n[7] Generate mesh")
    try:
        mech.run_python_script('Model.Mesh.ElementSize = Quantity("5 [mm]")')
        mech.run_python_script("Model.Mesh.GenerateMesh()")
        nodes = mech.run_python_script("Model.Mesh.Nodes.Count")
        elements = mech.run_python_script("Model.Mesh.Elements.Count")
        print(f"  Nodes: {nodes}, Elements: {elements}")
    except Exception as e:
        print(f"  Mesh error: {str(e)[:150]}")

    shot("e2e_7_meshed")

    # 8. Apply BCs + Solve
    print("\n[8] Apply BCs and solve")
    try:
        mech.run_python_script("analysis = Model.Analyses[0]")
        mech.run_python_script("fix = analysis.AddFixedSupport()")
        mech.run_python_script("pressure = analysis.AddPressure()")
        mech.run_python_script(
            'pressure.Magnitude.Output.SetDiscreteValue(0, Quantity("1 [MPa]"))'
        )
        print("  BCs applied. Solving...")
        status = mech.run_python_script(
            "analysis.Solve(True)\nstr(analysis.Solution.Status)"
        )
        print(f"  Status: {status}")
    except Exception as e:
        print(f"  BC/Solve error: {str(e)[:200]}")

    shot("e2e_8_solved")

    # 9. Results
    print("\n[9] Extract deformation")
    try:
        deform = mech.run_python_script(
            "sol = Model.Analyses[0].Solution\n"
            "d = sol.AddTotalDeformation()\n"
            "sol.EvaluateAllResults()\n"
            "str(d.Maximum)"
        )
        print(f"  Max deformation: {deform}")
    except Exception as e:
        print(f"  Result error: {str(e)[:200]}")

    shot("e2e_9_final")
    mech.exit()

    print("\n" + "=" * 60)
    print("E2E COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
