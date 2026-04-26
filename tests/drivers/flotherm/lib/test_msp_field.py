"""Binary-field reader tests — synthetic workspaces, no Flotherm required."""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import pytest

from sim.drivers.flotherm.lib.msp_field import (
    MspFieldError,
    list_fields,
    read_mesh_dims,
    read_msp_field,
)


def _make_workspace(
    tmp_path: Path,
    nx: int,
    ny: int,
    nz: int,
    fields: dict[str, np.ndarray],
    msp: int = 0,
) -> Path:
    """Build a fake Flotherm workspace at tmp_path/ws with the given fields."""
    ws = tmp_path / "ws"
    ds = ws / "DataSets" / "BaseSolution"
    pdtemp = ds / "PDTemp"
    pdtemp.mkdir(parents=True)
    end = ds / f"msp_{msp}" / "end"
    end.mkdir(parents=True)

    logit_text = (
        "Solver banner line 1\n"
        f"  domain 0 no. in x = {nx}  no. in y = {ny}  no. in z = {nz}\n"
        "Iteration progress lines etc.\n"
        "status 3 normal exit from main program MAINUU.\n"
    )
    (pdtemp / "logit").write_text(logit_text, encoding="utf-8")

    for name, arr in fields.items():
        flat = arr.astype("<f4").ravel(order="C")
        # Same 4-byte sentinel Flotherm uses (`00 00 00 00`)
        payload = b"\x00\x00\x00\x00" + flat.tobytes()
        (end / name).write_bytes(payload)

    return ws


def test_read_mesh_dims_parses_logit(tmp_path: Path):
    ws = _make_workspace(tmp_path, nx=19, ny=17, nz=9, fields={})
    assert read_mesh_dims(ws) == (19, 17, 9)


def test_read_mesh_dims_handles_variable_whitespace(tmp_path: Path):
    ws = tmp_path / "ws"
    pdtemp = ws / "DataSets" / "BaseSolution" / "PDTemp"
    pdtemp.mkdir(parents=True)
    (pdtemp / "logit").write_text(
        "domain 0 no. in x =25 no. in y =32 no. in z =25\n",
        encoding="utf-8",
    )
    assert read_mesh_dims(ws) == (25, 32, 25)


def test_read_mesh_dims_missing_logit_raises(tmp_path: Path):
    with pytest.raises(MspFieldError, match="not found"):
        read_mesh_dims(tmp_path / "nope")


def test_read_mesh_dims_unparseable_raises(tmp_path: Path):
    pdtemp = tmp_path / "DataSets" / "BaseSolution" / "PDTemp"
    pdtemp.mkdir(parents=True)
    (pdtemp / "logit").write_text("totally different content\n")
    with pytest.raises(MspFieldError, match="parse mesh dims"):
        read_mesh_dims(tmp_path)


def test_list_fields_empty_for_unsolved(tmp_path: Path):
    assert list_fields(tmp_path / "nope") == []


def test_list_fields_returns_sorted(tmp_path: Path):
    arr = np.zeros((9, 17, 19), dtype="<f4")
    ws = _make_workspace(tmp_path, 19, 17, 9, fields={
        "Temperature": arr, "Pressure": arr, "Speed": arr,
    })
    assert list_fields(ws) == ["Pressure", "Speed", "Temperature"]


def test_read_msp_field_round_trip_x_fastest(tmp_path: Path):
    nx, ny, nz = 4, 5, 3
    expected = np.arange(nx * ny * nz, dtype="<f4").reshape((nz, ny, nx))
    ws = _make_workspace(tmp_path, nx, ny, nz, fields={"Temperature": expected})
    result = read_msp_field(ws, "Temperature", reshape_order="x-fastest")
    assert result.shape == (nz, ny, nx)
    np.testing.assert_array_equal(result, expected)


def test_read_msp_field_round_trip_z_fastest(tmp_path: Path):
    nx, ny, nz = 4, 5, 3
    flat = np.arange(nx * ny * nz, dtype="<f4")
    # On disk we just write the flat sequence; the test is whether the
    # z-fastest reshape gives the requested (nx, ny, nz) layout.
    ws = _make_workspace(
        tmp_path, nx, ny, nz,
        fields={"Temperature": flat.reshape((nz, ny, nx))},
    )
    result = read_msp_field(ws, "Temperature", reshape_order="z-fastest")
    assert result.shape == (nx, ny, nz)


def test_read_msp_field_unknown_field_lists_available(tmp_path: Path):
    arr = np.zeros((3, 4, 5), dtype="<f4")
    ws = _make_workspace(tmp_path, 5, 4, 3, fields={"Temperature": arr})
    with pytest.raises(MspFieldError) as excinfo:
        read_msp_field(ws, "NotAField")
    msg = str(excinfo.value)
    assert "Temperature" in msg
    assert "NotAField" in msg


def test_read_msp_field_size_mismatch_raises(tmp_path: Path):
    """If the binary on disk doesn't match the logit's declared dims, error clearly."""
    ws = tmp_path / "ws"
    ds = ws / "DataSets" / "BaseSolution"
    pdtemp = ds / "PDTemp"
    pdtemp.mkdir(parents=True)
    (pdtemp / "logit").write_text(
        "domain 0 no. in x =5 no. in y =4 no. in z =3\n",
    )
    end = ds / "msp_0" / "end"
    end.mkdir(parents=True)
    # Wrong size — should be 4 + 4·5·4·3 = 244, write 100 instead
    (end / "Temperature").write_bytes(b"\x00" * 100)
    with pytest.raises(MspFieldError, match="Size mismatch"):
        read_msp_field(ws, "Temperature")


def test_read_msp_field_unknown_reshape_order_raises(tmp_path: Path):
    arr = np.zeros((3, 4, 5), dtype="<f4")
    ws = _make_workspace(tmp_path, 5, 4, 3, fields={"Temperature": arr})
    with pytest.raises(MspFieldError, match="Unknown reshape_order"):
        read_msp_field(ws, "Temperature", reshape_order="bogus")  # type: ignore[arg-type]


def test_known_temperature_values_round_trip(tmp_path: Path):
    """Verify dtype + endianness handling on a small known case."""
    nx, ny, nz = 2, 2, 2
    expected = np.array(
        [[[60.0, 60.0], [25.0, 25.0]],
         [[60.0, 60.0], [25.0, 25.0]]],
        dtype="<f4",
    )
    # expected has shape (nz=2, ny=2, nx=2) already
    ws = _make_workspace(tmp_path, nx, ny, nz, fields={"Temperature": expected})
    result = read_msp_field(ws, "Temperature")
    assert result.dtype == np.dtype("<f4")
    np.testing.assert_array_equal(result, expected)
    # Bytes-level check: header + 8 floats
    raw = (
        ws / "DataSets" / "BaseSolution" / "msp_0" / "end" / "Temperature"
    ).read_bytes()
    assert raw[:4] == b"\x00\x00\x00\x00"
    assert len(raw) == 4 + 4 * nx * ny * nz
    decoded = struct.unpack("<8f", raw[4:])
    assert decoded[0] == 60.0
    assert decoded[2] == 25.0
