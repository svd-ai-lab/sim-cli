# Fusion 360 Cookbook

Runnable live-session examples for `sim-plugin-fusion360`. Fusion scripts run
inside the Fusion GUI through `SimFusionBridge`; do not run them with host
Python.

## SpaceX Starship Stack

`starship_stack.py` creates an approximate Starship/Super Heavy vehicle using
public proportions from SpaceX: a 123 m integrated stack, 9 m diameter, 71 m
Super Heavy booster, and 52 m Starship upper stage. The Fusion model uses a
compact tabletop scale of `1 cm = 1 m`.

Live co-working loop:

```powershell
uv run sim connect --solver fusion360
# If Fusion reports "bridge not running", open Scripts and Add-Ins once,
# select SimFusionBridge, and press Run.
uv run sim exec --file cookbook/starship_stack.py --label starship-stack
```

After the script runs, use Fusion's normal Save/Save As flow if you want to keep
the document in a cloud project.
