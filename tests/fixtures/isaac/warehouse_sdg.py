"""L4: Warehouse SDG — load warehouse USD, 50 random camera views."""
import json
import os
from pathlib import Path

import torch  # noqa: F401  — preload before Kit corrupts DLL context
from isaacsim import SimulationApp

_EXP = os.path.join(os.environ["EXP_PATH"], "isaacsim.exp.full.kit")
simulation_app = SimulationApp(
    {"headless": True, "renderer": "RayTracedLighting"}, experience=_EXP,
)

import omni.replicator.core as rep
from omni.isaac.core.utils.nucleus import get_assets_root_path

OUT_DIR = Path(os.environ.get("ISAAC_OUT", "_output_l4")).resolve()
OUT_DIR.mkdir(parents=True, exist_ok=True)

assets = get_assets_root_path()
warehouse_usd = f"{assets}/Isaac/Environments/Simple_Warehouse/warehouse.usd"

with rep.new_layer():
    env = rep.create.from_usd(warehouse_usd)
    camera = rep.create.camera()
    render_product = rep.create.render_product(camera, (640, 480))

    with rep.trigger.on_frame(num_frames=50):
        with camera:
            rep.modify.pose(
                position=rep.distribution.uniform((-5, -5, 1), (5, 5, 3)),
                look_at=(0, 0, 1),
            )

    writer = rep.WriterRegistry.get("BasicWriter")
    writer.initialize(output_dir=str(OUT_DIR), rgb=True)
    writer.attach([render_product])

rep.orchestrator.run()
rep.orchestrator.wait_until_complete()

pngs = sorted(OUT_DIR.rglob("rgb_*.png"))

print(json.dumps({
    "level": "L4",
    "output_dir": str(OUT_DIR),
    "frames_rendered": len(pngs),
}), flush=True)

simulation_app.close()
