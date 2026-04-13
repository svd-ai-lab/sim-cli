"""Visual end-to-end test: Launch Workbench, create systems, verify via screenshots.

This script launches Workbench WITH GUI, creates analysis systems,
takes screenshots at each step, and writes structured results.
"""
import json
import os
import subprocess
import sys
import time


def screenshot(name: str) -> str:
    """Take a screenshot and save to C:/Temp/<name>.png."""
    path = f"C:\\Temp\\{name}.png"
    ps = f'''
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$screen = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bitmap = New-Object System.Drawing.Bitmap($screen.Width, $screen.Height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($screen.Location, [System.Drawing.Point]::Empty, $screen.Size)
$bitmap.Save('{path}')
$graphics.Dispose()
$bitmap.Dispose()
'''
    subprocess.run(["powershell", "-Command", ps], capture_output=True, timeout=10)
    print(f"  Screenshot: {path}")
    return path


def main():
    import ansys.workbench.core as pywb

    results = {}

    # === Step 0: Clean start ===
    print("Step 0: Launching Workbench with GUI...")
    wb = pywb.launch_workbench(release="241")
    print("  Launched. Waiting 8s for GUI to fully render...")
    time.sleep(8)
    screenshot("step0_launch")

    # === Step 1: Smoke test ===
    print("\nStep 1: Smoke test (trivial script)...")
    ret = wb.run_script_string('x = 1 + 1', log_level="warning")
    results["step1_smoke"] = {"ok": True, "return": str(ret)}
    print(f"  Result: {ret}")
    screenshot("step1_smoke")

    # === Step 2: Create Static Structural ===
    print("\nStep 2: Creating Static Structural system...")
    journal = '''
SetScriptVersion(Version="24.1")
template1 = GetTemplate(TemplateName="Static Structural", Solver="ANSYS")
system1 = template1.CreateSystem()

components = []
for comp_name in ["Engineering Data", "Geometry", "Model", "Setup", "Solution", "Results"]:
    try:
        container = system1.GetContainer(ComponentName=comp_name)
        components.append(comp_name)
    except:
        pass

import json, os, codecs
out = os.path.join(os.environ.get("TEMP", "C:/Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": len(components) == 6, "components": components, "count": len(components)}))
f.close()
'''
    wb.run_script_string(journal, log_level="warning")
    time.sleep(3)
    with open(os.path.join(os.environ["TEMP"], "sim_wb_result.json"), encoding="utf-8") as f:
        r2 = json.load(f)
    results["step2_static_structural"] = r2
    print(f"  Components: {r2.get('components')}")
    print(f"  OK: {r2.get('ok')}")
    screenshot("step2_static_structural")

    # === Step 3: Create Modal system ===
    print("\nStep 3: Creating Modal system...")
    journal3 = '''
SetScriptVersion(Version="24.1")
template1 = GetTemplate(TemplateName="Modal", Solver="ANSYS")
system1 = template1.CreateSystem()
components = []
for comp_name in ["Engineering Data", "Geometry", "Model", "Setup", "Solution", "Results"]:
    try:
        container = system1.GetContainer(ComponentName=comp_name)
        components.append(comp_name)
    except:
        pass
import json, os, codecs
out = os.path.join(os.environ.get("TEMP", "C:/Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": len(components) == 6, "components": components, "count": len(components)}))
f.close()
'''
    wb.run_script_string(journal3, log_level="warning")
    time.sleep(3)
    with open(os.path.join(os.environ["TEMP"], "sim_wb_result.json"), encoding="utf-8") as f:
        r3 = json.load(f)
    results["step3_modal"] = r3
    print(f"  OK: {r3.get('ok')}")
    screenshot("step3_modal")

    # === Step 4: Create Fluent system ===
    print("\nStep 4: Creating FLUENT system...")
    journal4 = '''
SetScriptVersion(Version="24.1")
template1 = GetTemplate(TemplateName="FLUENT")
system1 = template1.CreateSystem()
components = []
for comp_name in ["Setup", "Solution"]:
    try:
        container = system1.GetContainer(ComponentName=comp_name)
        components.append(comp_name)
    except:
        pass
import json, os, codecs
out = os.path.join(os.environ.get("TEMP", "C:/Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": len(components) == 2, "components": components, "count": len(components)}))
f.close()
'''
    wb.run_script_string(journal4, log_level="warning")
    time.sleep(3)
    with open(os.path.join(os.environ["TEMP"], "sim_wb_result.json"), encoding="utf-8") as f:
        r4 = json.load(f)
    results["step4_fluent"] = r4
    print(f"  OK: {r4.get('ok')}")
    screenshot("step4_fluent")

    # === Step 5: File transfer test ===
    print("\nStep 5: File upload/download round-trip...")
    test_content = "workbench_visual_test_content_12345"
    test_file = os.path.join(os.environ["TEMP"], "sim_visual_test.txt")
    with open(test_file, "w") as f:
        f.write(test_content)

    wb.upload_file(test_file)

    # Verify on server side
    journal5 = '''
import os, json, codecs
server_dir = os.environ.get("TEMP", "C:/Temp")
path = os.path.join(server_dir, "sim_visual_test.txt")
exists = os.path.isfile(path)
content = ""
if exists:
    f = open(path, "r")
    content = f.read()
    f.close()
out = os.path.join(server_dir, "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": exists and content == "workbench_visual_test_content_12345", "exists": exists, "content_match": content == "workbench_visual_test_content_12345"}))
f.close()
'''
    wb.run_script_string(journal5, log_level="warning")
    with open(os.path.join(os.environ["TEMP"], "sim_wb_result.json"), encoding="utf-8") as f:
        r5 = json.load(f)
    results["step5_file_transfer"] = r5
    print(f"  Upload exists: {r5.get('exists')}, Content match: {r5.get('content_match')}")
    screenshot("step5_file_transfer")

    # === Step 6: Start Mechanical server ===
    print("\nStep 6: Starting Mechanical server...")
    try:
        port = wb.start_mechanical_server(system_name="SYS")
        results["step6_mechanical_server"] = {"ok": True, "port": port}
        print(f"  Mechanical server started on port {port}")
    except Exception as e:
        results["step6_mechanical_server"] = {"ok": False, "error": str(e)[:200]}
        print(f"  Error: {e}")
    time.sleep(3)
    screenshot("step6_mechanical_server")

    # === Final summary ===
    print("\n" + "=" * 60)
    print("FINAL RESULTS:")
    all_ok = True
    for step, res in results.items():
        status = "PASS" if res.get("ok") else "FAIL"
        if not res.get("ok"):
            all_ok = False
        print(f"  {step}: {status}")
    print(f"\nOverall: {'ALL PASS' if all_ok else 'SOME FAILED'}")
    print("=" * 60)

    # Save final results
    with open(os.path.join(os.environ["TEMP"], "sim_wb_visual_results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    screenshot("step_final")


if __name__ == "__main__":
    main()
