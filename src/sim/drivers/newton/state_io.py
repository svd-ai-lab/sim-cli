"""State serialization via NumPy .npz.

A serialized State is a small bag of arrays:
  - body_q   (N, 7)  per-body pose [px, py, pz, qx, qy, qz, qw]
  - body_qd  (N, 6)  per-body spatial velocity
  - joint_q  (M,)    generalized coordinates
  - joint_qd (M,)    generalized velocities
  - particle_q / particle_qd — present for MPM/cloth/softbody examples

Optional fields are omitted gracefully if the State doesn't carry them.

This module imports `warp` and `newton` lazily inside functions so that sim's
main process can import it for type hints / path resolution without pulling
in CUDA.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

_FIELDS = (
    "body_q", "body_qd", "joint_q", "joint_qd",
    "particle_q", "particle_qd",
)


def save_state_npz(state: Any, path: str | Path) -> None:
    """Dump a newton.State to .npz. State may carry wp.array or numpy arrays."""
    import warp as wp  # noqa: PLC0415

    payload: dict[str, np.ndarray] = {}
    for field in _FIELDS:
        arr = getattr(state, field, None)
        if arr is None:
            continue
        if isinstance(arr, wp.array):
            payload[field] = arr.numpy()
        else:
            payload[field] = np.asarray(arr)
    np.savez(Path(path), **payload)


def load_state_npz_into(state: Any, path: str | Path) -> None:
    """Copy arrays from an .npz back into a freshly-allocated State."""
    import warp as wp  # noqa: PLC0415

    data = np.load(Path(path))
    for field in _FIELDS:
        if field not in data.files:
            continue
        target = getattr(state, field, None)
        if target is None:
            continue
        if isinstance(target, wp.array):
            target.assign(data[field])
        else:
            setattr(state, field, data[field])
