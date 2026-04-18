"""Subprocess entry point for the sim newton driver.

Invoked as:
    python <this_file> <script>

Runs as a standalone script (NOT via `-m sim.drivers.newton._entry`) so the
newton venv never has to import `sim.drivers` (which eagerly imports every
sibling driver and pulls in unrelated deps like httpx). At startup we insert
our own directory into sys.path so sibling modules (envelope, recipes,
sim_loop, state_io) import without the sim.drivers package machinery.

Dispatches on file suffix:
  .json → recipe interpreter → step loop → save_state_npz → envelope
  .py   → run the user's script; then rescan SIM_ARTIFACT_DIR → envelope

Emits a single `sim/newton/v1` envelope on stdout. Exit codes:
  0 on success
  2 on user error (bad args / missing script / bad recipe shape)
  3 on runtime error (solver exception, Warp/CUDA failure)
"""
from __future__ import annotations

import argparse
import os
import runpy
import sys
import time
import traceback
from pathlib import Path

# When invoked by file path, sys.path[0] is our directory. Be explicit so we
# still work if the caller has prepended other things.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from envelope import (  # noqa: E402
    EXIT_RUNTIME_ERROR,
    EXIT_USER_ERROR,
    emit_envelope,
    fail,
)


def _scan_artifacts(artifact_dir: Path) -> list[dict]:
    out: list[dict] = []
    if not artifact_dir.exists():
        return out
    for f in sorted(artifact_dir.rglob("*")):
        if not f.is_file():
            continue
        out.append({
            "path": str(f.resolve()),
            "size": f.stat().st_size,
            "kind": _kind_for(f.name),
        })
    return out


def _kind_for(name: str) -> str:
    lower = name.lower()
    if lower.endswith(".npz"):
        return "state"
    if lower.endswith((".png", ".jpg", ".jpeg")):
        return "render"
    if lower.endswith((".mp4", ".webm", ".gif")):
        return "video"
    if lower.endswith(".json"):
        return "meta"
    return "other"


def _merge_meta_json(artifact_dir: Path, data: dict) -> None:
    import json as _json

    meta = artifact_dir / "meta.json"
    if not meta.exists():
        return
    try:
        obj = _json.loads(meta.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return
    if not isinstance(obj, dict):
        return
    for k, v in obj.items():
        if k not in data:
            data[k] = v


def _run_recipe(script: Path, artifact_dir: Path) -> dict:
    from recipes import build_model_from_recipe
    from sim_loop import parse_solver_args, run_simulation
    from state_io import save_state_npz

    solver = os.environ.get("NEWTON_RECIPE_SOLVER", "SolverXPBD")
    num_frames = int(os.environ.get("NEWTON_RECIPE_FRAMES", "60"))
    fps = float(os.environ.get("NEWTON_RECIPE_FPS", "60"))
    substeps = int(os.environ.get("NEWTON_RECIPE_SUBSTEPS", "10"))
    device = os.environ.get("NEWTON_DEVICE") or None

    solver_args_raw = os.environ.get("NEWTON_SOLVER_ARGS", "")
    solver_kwargs = parse_solver_args(
        [p for p in solver_args_raw.split(";") if p.strip()]
    ) if solver_args_raw else {}

    model = build_model_from_recipe(script, device=device)
    final_state = run_simulation(
        model,
        solver_name=solver,
        num_frames=num_frames,
        fps=fps,
        substeps=substeps,
        solver_kwargs=solver_kwargs,
    )
    out_path = artifact_dir / "final.npz"
    save_state_npz(final_state, out_path)

    return {
        "state_path": str(out_path.resolve()),
        "solver": solver,
        "num_frames": num_frames,
        "fps": fps,
        "substeps": substeps,
        "body_count": int(getattr(model, "body_count", 0)),
        "joint_count": int(getattr(model, "joint_count", 0)),
        "shape_count": int(getattr(model, "shape_count", 0)),
    }


def _run_script(script: Path, artifact_dir: Path) -> dict:
    sys.argv = [str(script)]
    runpy.run_path(str(script), run_name="__main__")
    return {}


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sim-newton-entry")
    parser.add_argument("script", help="Path to .json recipe or .py script")
    args = parser.parse_args(argv)

    script = Path(args.script)
    if not script.exists():
        fail(EXIT_USER_ERROR, f"script not found: {script}")

    artifact_dir_env = os.environ.get("SIM_ARTIFACT_DIR") or os.environ.get(
        "NEWTON_CLI_ARTIFACT_DIR"
    )
    if not artifact_dir_env:
        fail(EXIT_USER_ERROR, "SIM_ARTIFACT_DIR env var not set by driver")
    artifact_dir = Path(artifact_dir_env)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    suffix = script.suffix.lower()
    start = time.monotonic()
    try:
        if suffix == ".json":
            data = _run_recipe(script, artifact_dir)
        elif suffix == ".py":
            data = _run_script(script, artifact_dir)
        else:
            fail(
                EXIT_USER_ERROR,
                f"unsupported file type: {script.suffix} (expected .py or .json)",
            )
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(traceback.format_exc())
        sys.stderr.flush()
        fail(EXIT_RUNTIME_ERROR, f"{type(e).__name__}: {e}")

    duration = time.monotonic() - start
    artifacts = _scan_artifacts(artifact_dir)
    data["artifact_dir"] = str(artifact_dir.resolve())
    data["artifacts"] = artifacts
    data["duration_s"] = round(duration, 4)
    _merge_meta_json(artifact_dir, data)

    emit_envelope(data)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
