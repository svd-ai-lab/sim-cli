"""L2: Load Franka articulation, read joint positions, print JSON."""
import json
import os

import torch  # noqa: F401  — preload before Kit corrupts DLL context
from isaacsim import SimulationApp

_EXP = os.path.join(os.environ["EXP_PATH"], "isaacsim.exp.full.kit")
simulation_app = SimulationApp({"headless": True}, experience=_EXP)

from omni.isaac.core import World
from omni.isaac.franka import Franka
import numpy as np

world = World(stage_units_in_meters=1.0)
franka = world.scene.add(Franka(prim_path="/World/Franka", name="franka"))
world.scene.add_default_ground_plane()
world.reset()

joint_positions = franka.get_joint_positions()
shape = list(joint_positions.shape)
nonzero = bool(np.any(joint_positions != 0))

for _ in range(30):
    world.step(render=False)

print(json.dumps({
    "level": "L2",
    "joint_positions_shape": shape,
    "joint_positions_nonzero": nonzero,
    "joint_count": int(shape[-1]) if shape else 0,
}), flush=True)

simulation_app.close()
