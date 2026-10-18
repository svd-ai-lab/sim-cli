"""Direct binary readback of `DataSets/BaseSolution/msp_<i>/end/<Field>` files.

Flotherm writes per-field 3D arrays as raw little-endian float32 prefixed
by a 4-byte sentinel. File size is exactly `4 + 4·nx·ny·nz`. Mesh dims are
parseable from `DataSets/BaseSolution/PDTemp/logit`.

This module is the binary-field reader called out in
[svd-ai-lab/sim-proj#48](https://github.com/svd-ai-lab/sim-proj/issues/48):
agent-readable results without going through the GUI.

Format claims verified 2026-04-26 across HBM_XSD_validation (20000 cells),
Mobile_Demo_Steady_State (2907 cells), HBM_3block_v1b_plus (300080 cells),
and HBM_3block_smoke_v1b (18125 cells) on Flotherm 2504.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import numpy as np

# Header is 4 bytes; observed value `00 00 00 00` on every solved file inspected
# so far (4 cases). Treat as opaque sentinel and skip — no record-marker semantics.
_HEADER_BYTES = 4

# Match `domain 0 no. in x =NN  no. in y =NN  no. in z =NN` — Flotherm prints
# this once per solver run after meshing. Whitespace is variable.
_DIMS_RE = re.compile(
    r"domain 0 no\. in x\s*=\s*(\d+)\s*no\. in y\s*=\s*(\d+)\s*no\. in z\s*=\s*(\d+)"
)

ReshapeOrder = Literal["x-fastest", "z-fastest"]


class MspFieldError(RuntimeError):
    """Raised when the binary readback can't proceed cleanly."""


def read_mesh_dims(workspace_dir: Path) -> tuple[int, int, int]:
    """Parse (nx, ny, nz) from `DataSets/BaseSolution/PDTemp/logit`.

    Raises MspFieldError if the file is missing or doesn't contain the
    expected line — both indicate the workspace isn't a solved Flotherm
    project.
    """
    logit = workspace_dir / "DataSets" / "BaseSolution" / "PDTemp" / "logit"
    if not logit.is_file():
        raise MspFieldError(
            f"PDTemp/logit not found at {logit} — workspace not solved?"
        )
    text = logit.read_text(encoding="utf-8", errors="replace")
    m = _DIMS_RE.search(text)
    if not m:
        raise MspFieldError(
            f"Could not parse mesh dims from {logit} — "
            "Flotherm log format may have changed."
        )
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def list_fields(workspace_dir: Path, msp: int = 0) -> list[str]:
    """Return the field filenames present in `msp_<msp>/end/`.

    On Flotherm 2504 the typical set is 11 files: Temperature, Pressure,
    Speed, X/Y/Z Velocity, X/Y/Z/Fluid Conductivity, TurbVis. Returns an
    empty list if the directory doesn't exist (workspace not solved).
    """
    end = workspace_dir / "DataSets" / "BaseSolution" / f"msp_{msp}" / "end"
    if not end.is_dir():
        return []
    return sorted(p.name for p in end.iterdir() if p.is_file())


def read_msp_field(
    workspace_dir: Path,
    field: str = "Temperature",
    msp: int = 0,
    reshape_order: ReshapeOrder = "x-fastest",
) -> np.ndarray:
    """Read a solved field as a (nz, ny, nx) NumPy array.

    Parameters
    ----------
    workspace_dir : Path
        The Flotherm project workspace, e.g.
        `<flouser>/<ProjectName>.<32-hex-hash>`.
    field : str
        One of the field names returned by `list_fields()`. Default
        "Temperature".
    msp : int
        Mesh-solve pass index. `0` is the steady-state or final transient
        pass — for a steady-state run, this is what you want.
    reshape_order : "x-fastest" | "z-fastest"
        Cell ordering. "x-fastest" treats the flat array as the last axis
        (x) varying fastest — i.e. C-order with shape (nz, ny, nx). The
        actual Flotherm convention is **not yet certified** on an
        asymmetric-mesh + Dirichlet-pinned reference case (see
        `sim-skills/flotherm/base/reference/postprocessing.md` §Cell
        ordering and units). Pass "z-fastest" if "x-fastest" puts pinned
        cells in the wrong place.

    Returns
    -------
    np.ndarray
        Shape `(nz, ny, nx)`, dtype `float32`. Always float32 LE on disk;
        NumPy reads it as native float32.

    Raises
    ------
    MspFieldError
        If the workspace isn't solved, the field isn't present, or the
        file size doesn't match `4 + 4·nx·ny·nz`.
    """
    nx, ny, nz = read_mesh_dims(workspace_dir)
    expected_size = _HEADER_BYTES + 4 * nx * ny * nz

    field_path = (
        workspace_dir / "DataSets" / "BaseSolution"
        / f"msp_{msp}" / "end" / field
    )
    if not field_path.is_file():
        available = list_fields(workspace_dir, msp=msp)
        raise MspFieldError(
            f"Field {field!r} not found at {field_path}. "
            f"Available: {available}"
        )

    raw = field_path.read_bytes()
    if len(raw) != expected_size:
        raise MspFieldError(
            f"Size mismatch for {field_path}: got {len(raw)} bytes, "
            f"expected {expected_size} (= 4 + 4·{nx}·{ny}·{nz})."
        )

    flat = np.frombuffer(raw, dtype="<f4", offset=_HEADER_BYTES)
    if reshape_order == "x-fastest":
        return flat.reshape((nz, ny, nx))
    elif reshape_order == "z-fastest":
        return flat.reshape((nx, ny, nz))
    else:
        raise MspFieldError(f"Unknown reshape_order: {reshape_order!r}")
