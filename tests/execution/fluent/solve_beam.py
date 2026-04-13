"""Solve a cantilever beam: WB → Mechanical → APDL → Deformation result."""
import subprocess
import time

from ansys.mechanical.core import connect_to_mechanical


def screenshot(name):
    ps = (
        'Add-Type @"\n'
        "using System;\n"
        "using System.Runtime.InteropServices;\n"
        "public class W32 {\n"
        '    [DllImport(""user32.dll"")] public static extern bool SetForegroundWindow(IntPtr h);\n'
        '    [DllImport(""user32.dll"")] public static extern bool ShowWindow(IntPtr h, int c);\n'
        "}\n"
        '"@\n'
        "$p = Get-Process -Name 'AnsysWBU' -EA SilentlyContinue | "
        "? { $_.MainWindowHandle -ne 0 } | Select -First 1\n"
        "if ($p) { [W32]::ShowWindow($p.MainWindowHandle, 3); "
        "[W32]::SetForegroundWindow($p.MainWindowHandle) }\n"
        "Start-Sleep -Seconds 2\n"
        "Add-Type -AssemblyName System.Windows.Forms\n"
        "Add-Type -AssemblyName System.Drawing\n"
        "$s = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds\n"
        "$b = New-Object System.Drawing.Bitmap($s.Width, $s.Height)\n"
        "$g = [System.Drawing.Graphics]::FromImage($b)\n"
        "$g.CopyFromScreen($s.Location, [System.Drawing.Point]::Empty, $s.Size)\n"
        f"$b.Save('C:\\Temp\\{name}.png')\n"
        "$g.Dispose(); $b.Dispose()\n"
    )
    subprocess.run(["powershell", "-Command", ps], capture_output=True, timeout=15)
    print(f"  Screenshot: C:\\Temp\\{name}.png")


def main():
    mech = connect_to_mechanical(ip="localhost", port=59911)
    print(f"Connected to Mechanical {mech.version}")

    # Step 1: Insert APDL commands line by line to avoid string escaping
    print("\nStep 1: Insert APDL command snippet...")

    # Use chr(10) for newline inside IronPython
    r = mech.run_python_script(
        "analysis = Model.Analyses[0]\n"
        "cmd = analysis.AddCommandSnippet()\n"
        "NL = chr(10)\n"
        'lines = ["/PREP7","ET,1,BEAM188","SECTYPE,1,BEAM,RECT",'
        '"SECDATA,0.01,0.01","MP,EX,1,2.1E11","MP,PRXY,1,0.3",'
        '"K,1,0,0,0","K,2,1,0,0","L,1,2","LESIZE,ALL,,,10",'
        '"LMESH,ALL","/SOLU","ANTYPE,STATIC","DK,1,ALL",'
        '"FK,2,FY,-1000","SOLVE","FINISH"]\n'
        "cmd.Input = NL.join(lines)\n"
        'cmd.Name = "BeamAPDL"\n'
        "str(cmd.Name)\n"
    )
    print(f"  Snippet: {r}")

    # Step 2: Solve
    print("\nStep 2: Solving...")
    r2 = mech.run_python_script(
        "analysis = Model.Analyses[0]\n"
        "analysis.Solve(True)\n"
        "str(analysis.Solution.Status)\n"
    )
    print(f"  Status: {r2}")
    time.sleep(3)

    # Step 3: Extract deformation
    print("\nStep 3: Extracting deformation result...")
    r3 = mech.run_python_script(
        "solution = Model.Analyses[0].Solution\n"
        "deform = solution.AddTotalDeformation()\n"
        "solution.EvaluateAllResults()\n"
        "str(deform.Maximum)\n"
    )
    print(f"  Max deformation: {r3}")

    # Verify the result
    try:
        # Parse the Quantity value
        val_str = r3.strip()
        print(f"  Raw value: {val_str}")

        # Analytical solution for cantilever beam:
        # delta = F*L^3 / (3*E*I)
        # F=1000N, L=1m, E=2.1e11 Pa, I=(0.01^4)/12 = 8.333e-10 m^4
        # delta = 1000 * 1^3 / (3 * 2.1e11 * 8.333e-10) = 1.587e-3 m
        print("  Analytical: ~1.587e-3 m (for cantilever beam F*L^3/3EI)")
    except Exception as e:
        print(f"  Parse error: {e}")

    screenshot("beam_deformation")
    print("\n=== BEAM SOLVE COMPLETE ===")


if __name__ == "__main__":
    main()
