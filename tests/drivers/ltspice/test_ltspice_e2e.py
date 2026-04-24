"""End-to-end LTspice batch test.

Skipped unless a real LTspice install is visible. Runs the shipped RC
low-pass fixture, then asserts that the driver extracted the .MEAS
value from the UTF-16 log and named traces from the binary .raw.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from sim.drivers.ltspice import LTspiceDriver

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"


@pytest.mark.integration
def test_ltspice_batch_rc_transient(tmp_path):
    driver = LTspiceDriver()
    if driver.connect().status != "ok":
        pytest.skip("LTspice not installed on this host")

    # Copy the fixture into tmp_path — LTspice writes .log and .raw beside
    # the netlist, so we keep the repo fixture dir clean.
    netlist = tmp_path / "rc.net"
    shutil.copyfile(FIXTURES / "ltspice_good.net", netlist)

    result = driver.run_file(netlist)
    assert result.exit_code == 0, f"stderr: {result.stderr}"

    parsed = driver.parse_output(result.stdout)
    assert "vout_pk" in parsed["measures"], parsed
    assert parsed["measures"]["vout_pk"]["value"] == pytest.approx(1.0, rel=5e-3)
    assert "V(out)" in parsed["traces"]
    assert parsed["log"] and Path(parsed["log"]).is_file()
    assert parsed["raw"] and Path(parsed["raw"]).is_file()
