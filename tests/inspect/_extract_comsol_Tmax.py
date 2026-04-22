"""Load the saved .mph and extract Tmax/Tmin via mph library.

This is the post-hoc extract — the in-session MaxMinVolume feature
rejects creation for reasons tied to COMSOL's UI-side
"measurement feature" scenario flag. Reading the saved model with
mph.load() bypasses that and evaluates directly.
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

MPH_PATH = Path(
    os.environ.get("USERPROFILE", r"C:\Users\Administrator")
) / "Desktop" / "surface_mount_package.mph"

if not MPH_PATH.is_file():
    print(f"ABORT — not found: {MPH_PATH}")
    sys.exit(1)

print(f"loading .mph: {MPH_PATH}  ({MPH_PATH.stat().st_size:,} bytes)")

os.environ.setdefault("COMSOL_USER", "sim")
os.environ.setdefault("COMSOL_PASSWORD", "sim")

import mph  # noqa: E402

client = mph.start(cores=2, version="6.4")
print(f"mph client ready: version={client.version}")

model = client.load(str(MPH_PATH))
print(f"model loaded: {model.name()}")

# Evaluate T at all solution nodes over comp1 domains.
# mph.Model.evaluate returns numpy array over all mesh nodes when dataset is default.
import numpy as np

T_arr = model.evaluate("T-273.15")
T_arr = np.asarray(T_arr)
print(f"eval shape: {T_arr.shape}  dtype={T_arr.dtype}")

# If 2D, flatten
if T_arr.ndim > 1:
    T_arr = T_arr.flatten()

Tmax = float(np.max(T_arr))
Tmin = float(np.min(T_arr))
Tmean = float(np.mean(T_arr))
n_nodes = T_arr.size

ref = 45.8
delta = Tmax - ref

print("\n" + "=" * 60)
print(f"  Result extraction from {MPH_PATH.name}")
print("=" * 60)
print(f"  nodes evaluated      : {n_nodes:,}")
print(f"  Tmax (chip hot spot) : {Tmax:6.2f} degC")
print(f"  Tmin (board corner)  : {Tmin:6.2f} degC")
print(f"  Tmean                : {Tmean:6.2f} degC")
print(f"  Reference chip max T : {ref:6.2f} degC   (COMSOL Appl Lib 847)")
print(f"  Delta vs reference   : {delta:+6.2f} degC")
print("=" * 60)

out = {
    "source_mph": str(MPH_PATH),
    "nodes_evaluated": n_nodes,
    "Tmax_degC": Tmax,
    "Tmin_degC": Tmin,
    "Tmean_degC": Tmean,
    "reference_Tmax_degC": ref,
    "delta_degC": delta,
}

out_path = Path(__file__).parent / "_run_outputs" / "comsol_Tmax_from_mph.json"
out_path.write_text(json.dumps(out, indent=2))
print(f"\n[trace] {out_path}")

client.clear()
client.disconnect()
