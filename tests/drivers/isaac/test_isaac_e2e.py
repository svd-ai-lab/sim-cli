"""Progressive E2E: L1 → L2 → L3 → L4. Skip if Isaac not available."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sim.drivers.isaac import IsaacDriver

FIX = Path(__file__).parent.parent.parent / "fixtures" / "isaac"
EXEC_DIR = Path(__file__).parent.parent.parent / "execution" / "isaac"
EXEC_DIR.mkdir(parents=True, exist_ok=True)


@pytest.fixture(scope="module")
def driver() -> IsaacDriver:
    return IsaacDriver()


def _require_isaac(driver: IsaacDriver) -> None:
    if driver.connect().status != "ok":
        pytest.skip("Isaac Sim not installed (set ISAAC_VENV)")


def _has_gpu() -> bool:
    try:
        out = subprocess.run(
            ["nvidia-smi"], capture_output=True, text=True, timeout=5,
        )
        return out.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _write_summary(name: str, data: dict) -> None:
    (EXEC_DIR / f"{name}_summary.json").write_text(json.dumps(data, indent=2))


@pytest.mark.serial
@pytest.mark.slow
class TestL1HelloWorld:
    def test_cube_falls(self, driver):
        _require_isaac(driver)
        result = driver.run_file(FIX / "hello_world.py")
        parsed = driver.parse_output(result.stdout)
        _write_summary("L1_hello_world", {
            "exit_code": result.exit_code,
            "duration_s": result.duration_s,
            "parsed": parsed,
            "stderr_tail": result.stderr[-500:] if result.stderr else "",
        })
        assert result.exit_code == 0, f"stderr: {result.stderr[-500:]}"
        assert parsed.get("level") == "L1"
        assert parsed.get("delta_z_m", 0) > 1.0, \
            f"cube should fall >1 m in 60 frames, got {parsed.get('delta_z_m')}"


@pytest.mark.serial
@pytest.mark.slow
class TestL2Franka:
    def test_franka_joints(self, driver):
        _require_isaac(driver)
        result = driver.run_file(FIX / "import_franka.py")
        parsed = driver.parse_output(result.stdout)
        _write_summary("L2_franka", {
            "exit_code": result.exit_code,
            "duration_s": result.duration_s,
            "parsed": parsed,
            "stderr_tail": result.stderr[-500:] if result.stderr else "",
        })
        assert result.exit_code == 0, f"stderr: {result.stderr[-500:]}"
        assert parsed.get("level") == "L2"
        assert parsed.get("joint_count", 0) >= 7, \
            f"Franka should have >=7 joints, got {parsed.get('joint_count')}"
        assert parsed.get("joint_positions_nonzero") is True


@pytest.mark.serial
@pytest.mark.slow
class TestL3Replicator:
    def test_cubes_render(self, driver, tmp_path, monkeypatch):
        _require_isaac(driver)
        if not _has_gpu():
            pytest.skip("No NVIDIA GPU detected; Replicator needs RTX")
        out = tmp_path / "rep_out"
        monkeypatch.setenv("ISAAC_OUT", str(out))
        result = driver.run_file(FIX / "replicator_cubes.py")
        parsed = driver.parse_output(result.stdout)
        _write_summary("L3_replicator", {
            "exit_code": result.exit_code,
            "duration_s": result.duration_s,
            "parsed": parsed,
            "stderr_tail": result.stderr[-500:] if result.stderr else "",
        })
        assert result.exit_code == 0, f"stderr: {result.stderr[-500:]}"
        assert parsed.get("level") == "L3"
        assert parsed.get("frames_rendered", 0) == 20, \
            f"expected 20 frames, got {parsed.get('frames_rendered')}"
        out_dir = Path(parsed["output_dir"])
        pngs = list(out_dir.rglob("rgb_*.png"))
        assert len(pngs) == 20


@pytest.mark.serial
@pytest.mark.slow
class TestOfficialHelloWorld:
    """Verbatim-adapted NVIDIA 4.5 Hello World tutorial.

    Source: https://docs.isaacsim.omniverse.nvidia.com/4.5.0/core_api_tutorials/tutorial_core_hello_world.html
    """
    def test_official_hello_world(self, driver):
        _require_isaac(driver)
        result = driver.run_file(FIX / "official_hello_world.py")
        parsed = driver.parse_output(result.stdout)
        _write_summary("official_hello_world", {
            "exit_code": result.exit_code,
            "duration_s": result.duration_s,
            "parsed": parsed,
        })
        assert result.exit_code == 0, f"stderr: {result.stderr[-500:]}"
        assert parsed.get("tutorial") == "hello_world_4_5_official"
        # Cube starts at z=1.0, has scale 0.5015 → rests at z≈0.25 on ground
        assert parsed.get("delta_z_m", 0) > 0.5
        # After 500 frames, cube should be resting (velocity near zero)
        vel = parsed.get("final_linear_velocity", [1, 1, 1])
        assert all(abs(v) < 0.1 for v in vel), f"cube still moving: {vel}"


@pytest.mark.serial
@pytest.mark.slow
class TestL4Warehouse:
    def test_warehouse_sdg(self, driver, tmp_path, monkeypatch):
        _require_isaac(driver)
        if not _has_gpu():
            pytest.skip("No NVIDIA GPU detected; Replicator needs RTX")
        out = tmp_path / "warehouse_out"
        monkeypatch.setenv("ISAAC_OUT", str(out))
        result = driver.run_file(FIX / "warehouse_sdg.py")
        parsed = driver.parse_output(result.stdout)
        _write_summary("L4_warehouse", {
            "exit_code": result.exit_code,
            "duration_s": result.duration_s,
            "parsed": parsed,
            "stderr_tail": result.stderr[-500:] if result.stderr else "",
        })
        # Relaxed: exit 0 + at least 10 images
        assert result.exit_code == 0, f"stderr: {result.stderr[-500:]}"
        frames = parsed.get("frames_rendered", 0)
        assert frames >= 10, f"expected >=10 frames for L4 relaxed, got {frames}"
