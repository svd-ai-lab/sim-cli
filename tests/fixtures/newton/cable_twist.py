"""Route-B fixture: cable_twist via newton.examples (VBD).

Drives Newton's built-in `cable_twist` example in headless/--test mode, then
dumps the final simulation state to SIM_ARTIFACT_DIR/final.npz so the sim
driver can list it as an artifact.

No arguments — solver/framecount are hardcoded to keep the fixture small and
the test fast. Bumping num_frames above ~20 makes this >60s on CPU.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

import newton.examples

EXAMPLE_NAME = "cable_twist"
NUM_FRAMES = "20"

sys.argv = [
    "newton.examples",
    EXAMPLE_NAME,
    "--viewer", "null",
    "--test",
    "--num-frames", NUM_FRAMES,
]

_captured: dict = {}
_orig_run = newton.examples.run


def _capturing_run(example, args):
    _captured["example"] = example
    _captured["args"] = args
    return _orig_run(example, args)


newton.examples.run = _capturing_run
newton.examples.main()

artifact_dir = Path(
    os.environ.get("SIM_ARTIFACT_DIR")
    or os.environ.get("NEWTON_CLI_ARTIFACT_DIR", ".")
)
artifact_dir.mkdir(parents=True, exist_ok=True)

example = _captured.get("example")
if example is None:
    print("WARN: newton.examples.run never invoked; nothing to save", file=sys.stderr)
    sys.exit(0)

state = (
    getattr(example, "state_0", None)
    or getattr(example, "state", None)
    or getattr(example, "state_in", None)
)
saved: dict = {}
if state is not None:
    for name in ("body_q", "body_qd", "joint_q", "joint_qd", "particle_q", "particle_qd"):
        arr = getattr(state, name, None)
        if arr is None:
            continue
        try:
            saved[name] = arr.numpy()
        except Exception:  # noqa: BLE001
            pass

if saved:
    np.savez(artifact_dir / "final.npz", **saved)
    print(f"OK — saved {len(saved)} arrays to {artifact_dir / 'final.npz'}")
else:
    print(f"OK — {EXAMPLE_NAME!r} ran but no state arrays captured")
