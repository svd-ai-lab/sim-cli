"""CFX Session E2E: step-by-step interactive post-processing of VMFL015.

This script launches a cfx5post -line session on the VMFL015 results,
executes a series of commands, records the input/output at each step,
and saves the full transcript + evidence images.

Usage:
    uv run python tests/execution/cfx/test_cfx_session_e2e.py
"""
import json
import time
from pathlib import Path

from sim.drivers.cfx import CfxDriver

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RES_FILE = Path(r"E:\CFX_tutorial\test_case_to_rrh\test_case_to_rrh\VMFL015_CFX\input\015_001.res")
EVIDENCE_DIR = Path(r"E:\simcli\sim-skills\cfx\base\workflows\vmfl015\evidence")
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

transcript: list[dict] = []


def record_step(step_num: int, description: str, command: str, result: dict):
    """Record a step in the transcript."""
    entry = {
        "step": step_num,
        "description": description,
        "command": command,
        "result": result,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    transcript.append(entry)

    ok_marker = "OK" if result.get("ok", True) else "FAIL"
    print(f"\n{'='*70}")
    print(f"Step {step_num}: {description} [{ok_marker}]")
    print(f"  Command: {command}")
    stdout = result.get("stdout", "")
    if stdout:
        for line in stdout.split("\n")[:10]:
            print(f"  > {line}")
    if "result" in result and result["result"]:
        print(f"  Result: {result['result']}")
    if "error" in result:
        print(f"  Error: {result['error']}")
    if "value" in result:
        print(f"  Value: {result['value']} [{result.get('units', '')}]")


def main():
    driver = CfxDriver()
    step = 0

    # ------------------------------------------------------------------
    # Step 1: Launch session (skip solve, use existing .res)
    # ------------------------------------------------------------------
    step += 1
    print(f"\nLaunching CFX session with {RES_FILE}...")
    launch_info = driver.launch(res_file=str(RES_FILE), skip_solve=True)
    record_step(step, "Launch cfx5post session on VMFL015 results",
                f"driver.launch(res_file={RES_FILE.name})", launch_info)

    if not launch_info.get("ok"):
        print("FAILED to launch session!")
        return

    # ------------------------------------------------------------------
    # Step 2: Query available boundaries
    # ------------------------------------------------------------------
    step += 1
    boundaries = driver.query("session.boundaries")
    record_step(step, "Query available boundaries",
                "driver.query('session.boundaries')", boundaries)

    # ------------------------------------------------------------------
    # Step 3: Query available variables
    # ------------------------------------------------------------------
    step += 1
    variables = driver.query("session.variables")
    # Trim to first 20 for readability
    trimmed = dict(variables)
    if "variables" in trimmed and len(trimmed["variables"]) > 20:
        trimmed["variables"] = trimmed["variables"][:20] + [f"... ({len(variables['variables'])} total)"]
    record_step(step, "Query available result variables",
                "driver.query('session.variables')", trimmed)

    # ------------------------------------------------------------------
    # Step 4: Evaluate mass flow at inlet
    # ------------------------------------------------------------------
    step += 1
    r = driver.run("evaluate(massFlow()@inlet)", label="mass_flow_inlet")
    record_step(step, "Evaluate mass flow at inlet (should be 1.379 kg/s)",
                "evaluate(massFlow()@inlet)", r)

    # ------------------------------------------------------------------
    # Step 5: Evaluate mass flow at outlet (conservation check)
    # ------------------------------------------------------------------
    step += 1
    r = driver.run("evaluate(massFlow()@outlet)", label="mass_flow_outlet")
    record_step(step, "Evaluate mass flow at outlet (should be -1.379 kg/s, conservation)",
                "evaluate(massFlow()@outlet)", r)

    # ------------------------------------------------------------------
    # Step 6: Evaluate area-average pressure at inlet
    # ------------------------------------------------------------------
    step += 1
    r = driver.run("evaluate(areaAve(Pressure)@inlet)", label="pressure_inlet")
    record_step(step, "Area-average pressure at inlet",
                "evaluate(areaAve(Pressure)@inlet)", r)

    # ------------------------------------------------------------------
    # Step 7: Evaluate area-average pressure at outlet
    # ------------------------------------------------------------------
    step += 1
    r = driver.run("evaluate(areaAve(Pressure)@outlet)", label="pressure_outlet")
    record_step(step, "Area-average pressure at outlet (should be ~0 Pa)",
                "evaluate(areaAve(Pressure)@outlet)", r)

    # ------------------------------------------------------------------
    # Step 8: Evaluate area-average velocity at inlet
    # ------------------------------------------------------------------
    step += 1
    r = driver.run("evaluate(areaAve(Velocity)@inlet)", label="velocity_inlet")
    record_step(step, "Area-average velocity at inlet",
                "evaluate(areaAve(Velocity)@inlet)", r)

    # ------------------------------------------------------------------
    # Step 9: Evaluate max pressure in domain
    # ------------------------------------------------------------------
    step += 1
    r = driver.run("evaluate(maxVal(Pressure)@Default Domain)", label="max_pressure")
    record_step(step, "Max pressure in domain",
                "evaluate(maxVal(Pressure)@Default Domain)", r)

    # ------------------------------------------------------------------
    # Step 10: Evaluate min pressure in domain
    # ------------------------------------------------------------------
    step += 1
    r = driver.run("evaluate(minVal(Pressure)@Default Domain)", label="min_pressure")
    record_step(step, "Min pressure in domain",
                "evaluate(minVal(Pressure)@Default Domain)", r)

    # ------------------------------------------------------------------
    # Step 11: Evaluate area at inlet and outlet
    # ------------------------------------------------------------------
    step += 1
    r = driver.run("evaluate(area()@inlet)", label="area_inlet")
    record_step(step, "Inlet area",
                "evaluate(area()@inlet)", r)

    step += 1
    r = driver.run("evaluate(area()@outlet)", label="area_outlet")
    record_step(step, "Outlet area",
                "evaluate(area()@outlet)", r)

    # ------------------------------------------------------------------
    # Step 13: Create pressure contour on walls
    # ------------------------------------------------------------------
    step += 1
    ccl = """CONTOUR: SessionPressure
  Colour Map = Default Colour Map
  Colour Variable = Pressure
  Contour Range = Global
  Domain List = All Domains
  Fringe Fill = On
  Location List = Default Domain Default
  Number of Contours = 20
  Surface Drawing = Smooth Shading
  Visibility = On
END"""
    r = driver.run(ccl, label="create_pressure_contour")
    record_step(step, "Create pressure contour on domain walls",
                "enterccl: CONTOUR: SessionPressure ...", r)

    # ------------------------------------------------------------------
    # Step 14: Export pressure contour image
    # ------------------------------------------------------------------
    step += 1
    img_path = str(EVIDENCE_DIR / "session_pressure.png")
    ccl = f"""HARDCOPY:
  Hardcopy Filename = {img_path}
  Hardcopy Format = png
  Image Height = 1200
  Image Width = 1600
  White Background = On
END
>print"""
    r = driver.run(ccl, label="export_pressure_image")
    # Check image exists
    img_exists = Path(img_path).is_file()
    img_size = Path(img_path).stat().st_size if img_exists else 0
    r["image_file"] = img_path
    r["image_exists"] = img_exists
    r["image_size_bytes"] = img_size
    record_step(step, f"Export pressure contour image ({img_size} bytes)",
                "enterccl: HARDCOPY + >print", r)

    # ------------------------------------------------------------------
    # Step 15: Switch to velocity contour
    # ------------------------------------------------------------------
    step += 1
    ccl = """CONTOUR: SessionPressure
  Colour Variable = Velocity
END"""
    r = driver.run(ccl, label="switch_to_velocity")
    record_step(step, "Switch contour to velocity", "enterccl: Colour Variable = Velocity", r)

    # ------------------------------------------------------------------
    # Step 16: Export velocity contour image
    # ------------------------------------------------------------------
    step += 1
    img_path2 = str(EVIDENCE_DIR / "session_velocity.png")
    ccl = f"""HARDCOPY:
  Hardcopy Filename = {img_path2}
  Hardcopy Format = png
  Image Height = 1200
  Image Width = 1600
  White Background = On
END
>print"""
    r = driver.run(ccl, label="export_velocity_image")
    img_exists2 = Path(img_path2).is_file()
    img_size2 = Path(img_path2).stat().st_size if img_exists2 else 0
    r["image_file"] = img_path2
    r["image_exists"] = img_exists2
    r["image_size_bytes"] = img_size2
    record_step(step, f"Export velocity contour image ({img_size2} bytes)",
                "enterccl: HARDCOPY + >print", r)

    # ------------------------------------------------------------------
    # Step 17: Disconnect
    # ------------------------------------------------------------------
    step += 1
    r = driver.disconnect()
    record_step(step, "Disconnect session", "driver.disconnect()", r)

    # ------------------------------------------------------------------
    # Save transcript
    # ------------------------------------------------------------------
    transcript_path = EVIDENCE_DIR / "session_e2e_transcript.json"
    with open(transcript_path, "w", encoding="utf-8") as f:
        json.dump(transcript, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*70}")
    print(f"E2E SESSION TEST COMPLETE: {step} steps")
    print(f"Transcript saved to: {transcript_path}")
    print(f"Evidence images: {EVIDENCE_DIR}")

    # Summary
    ok_count = sum(1 for t in transcript if t["result"].get("ok", True))
    fail_count = len(transcript) - ok_count
    print(f"Results: {ok_count} OK, {fail_count} FAIL")


if __name__ == "__main__":
    main()
