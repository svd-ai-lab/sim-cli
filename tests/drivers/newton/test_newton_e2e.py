"""End-to-end tests for the newton driver.

Each test invokes `NewtonDriver.run_file` against a fixture, expecting Newton
actually installed (either via env vars or in sys.executable). If no newton
interpreter is reachable, the whole module skips.

All three fixtures map to one of newton-cli's canonical examples:
  basic_pendulum — Route A, recipe JSON, SolverXPBD on CPU
  robot_g1       — Route A, recipe JSON with MJCF importer, SolverMuJoCo
  cable_twist    — Route B, run-script via newton.examples (VBD)
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest

from sim.drivers.newton import NewtonDriver

pytestmark = pytest.mark.integration

FIX = Path(__file__).parent.parent.parent / "fixtures" / "newton"

# Default venv that already has newton 1.2 + warp-lang 1.12 installed.
_DEFAULT_NEWTON_VENV = Path("E:/newton-cli/newton_cli/.venv")


@pytest.fixture(scope="module", autouse=True)
def _ensure_newton_venv():
    """Point NEWTON_VENV at the reference install if not already set."""
    if os.environ.get("NEWTON_PYTHON") or os.environ.get("NEWTON_VENV"):
        yield
        return
    if _DEFAULT_NEWTON_VENV.exists():
        os.environ["NEWTON_VENV"] = str(_DEFAULT_NEWTON_VENV)
        yield
        os.environ.pop("NEWTON_VENV", None)
    else:
        pytest.skip(
            "No newton install available. "
            "Set NEWTON_VENV or NEWTON_PYTHON to a venv with `newton` + `warp-lang`."
        )


@pytest.fixture(scope="module")
def driver() -> NewtonDriver:
    d = NewtonDriver()
    if not d.detect_installed():
        pytest.skip("detect_installed() returned nothing — newton not reachable")
    return d


def _run_and_parse(driver: NewtonDriver, script: Path) -> tuple[dict, str, str, int]:
    result = driver.run_file(script)
    data = driver.parse_output(result.stdout)
    return data, result.stdout, result.stderr, result.exit_code


class TestBasicPendulumRecipe:
    def test_runs_end_to_end(self, driver):
        # Small override: 20 frames is enough to prove the pipeline.
        os.environ["NEWTON_RECIPE_FRAMES"] = "20"
        os.environ["NEWTON_DEVICE"] = "cpu"
        try:
            data, stdout, stderr, rc = _run_and_parse(
                driver, FIX / "basic_pendulum.json"
            )
        finally:
            os.environ.pop("NEWTON_RECIPE_FRAMES", None)
            os.environ.pop("NEWTON_DEVICE", None)

        assert rc == 0, f"exit {rc}\nstdout:\n{stdout}\nstderr:\n{stderr}"
        assert data, f"envelope missing from stdout:\n{stdout}"
        assert data["solver"] == "SolverXPBD"
        assert data["num_frames"] == 20
        assert data["body_count"] == 2
        assert data["joint_count"] == 2

        state_path = Path(data["state_path"])
        assert state_path.exists()
        arrays = np.load(state_path)
        assert "body_q" in arrays.files
        assert arrays["body_q"].shape == (2, 7)


class TestRobotG1Recipe:
    def test_runs_end_to_end(self, driver):
        os.environ["NEWTON_RECIPE_SOLVER"] = "SolverMuJoCo"
        os.environ["NEWTON_RECIPE_FRAMES"] = "10"
        os.environ["NEWTON_RECIPE_FPS"] = "60"
        os.environ["NEWTON_RECIPE_SUBSTEPS"] = "2"
        try:
            data, stdout, stderr, rc = _run_and_parse(
                driver, FIX / "robot_g1.json"
            )
        finally:
            os.environ.pop("NEWTON_RECIPE_SOLVER", None)
            os.environ.pop("NEWTON_RECIPE_FRAMES", None)
            os.environ.pop("NEWTON_RECIPE_FPS", None)
            os.environ.pop("NEWTON_RECIPE_SUBSTEPS", None)

        assert rc == 0, f"exit {rc}\nstdout:\n{stdout}\nstderr:\n{stderr}"
        assert data, f"envelope missing from stdout:\n{stdout}"
        assert data["body_count"] > 10
        assert data["joint_count"] > 10
        assert Path(data["state_path"]).exists()


class TestCableTwistRunScript:
    def test_runs_end_to_end(self, driver):
        data, stdout, stderr, rc = _run_and_parse(driver, FIX / "cable_twist.py")
        assert rc == 0, f"exit {rc}\nstdout:\n{stdout}\nstderr:\n{stderr}"
        assert data, f"envelope missing from stdout:\n{stdout}"
        artifacts = data.get("artifacts") or []
        npz = [a for a in artifacts if a["kind"] == "state"]
        assert npz, f"no state artifact listed in:\n{json.dumps(data, indent=2)}"
        assert Path(npz[0]["path"]).exists()
