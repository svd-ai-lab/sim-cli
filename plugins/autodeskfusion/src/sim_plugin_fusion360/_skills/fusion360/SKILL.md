# Fusion 360 via sim

Use this skill when working with Autodesk Fusion 360 through `sim`. Fusion's
`adsk` Python API runs inside the Fusion GUI process, so treat this as a live
human/AI co-working session rather than a headless batch solver.

## Workflow

1. Ask the human to keep Fusion visible when one-time dialogs appear.
2. Use `uv run sim connect fusion360` from the project environment, or
   `launch()` from Python, to install the `SimFusionBridge` add-in resources.
3. If the bridge is not running, tell the human exactly once: open **Scripts
   and Add-Ins**, select `SimFusionBridge`, and press **Run**.
4. Execute short, reviewable Python snippets or scripts.
5. After each GUI-visible action, capture a screenshot and inspect the JSON
   artifact before continuing.

## Scope

- Good first targets: Design workspace model edits, document/body/sketch
  inspection, export probes, and visible co-editing.
- Do not assume Fusion Simulation workspace solve automation exists until a
  real `adsk.sim` probe proves it.
- Do not import `adsk` from host Python; it is provided by Fusion inside the
  GUI process.
