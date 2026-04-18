"""Official Isaac Sim 4.5.0 Hello World tutorial (headless-adapted + JSON output).

Source: https://docs.isaacsim.omniverse.nvidia.com/4.5.0/core_api_tutorials/tutorial_core_hello_world.html
Verbatim structure using the 4.5 isaacsim.core.api.* namespace; adapted to
headless=True + JSON emission for sim-cli acceptance checks.
"""
import json
import os

import torch  # noqa: F401  — preload before Kit corrupts DLL context
from isaacsim import SimulationApp

_EXP = os.path.join(os.environ["EXP_PATH"], "isaacsim.exp.full.kit")
simulation_app = SimulationApp({"headless": True}, experience=_EXP)

from isaacsim.core.api import World
from isaacsim.core.api.objects import DynamicCuboid
import numpy as np

world = World()
world.scene.add_default_ground_plane()
fancy_cube = world.scene.add(
    DynamicCuboid(
        prim_path="/World/random_cube",
        name="fancy_cube",
        position=np.array([0, 0, 1.0]),
        scale=np.array([0.5015, 0.5015, 0.5015]),
        color=np.array([0, 0, 1.0]),
    ))

world.reset()

start_pos, _ = fancy_cube.get_world_pose()
final_velocity = None
for i in range(500):
    position, orientation = fancy_cube.get_world_pose()
    linear_velocity = fancy_cube.get_linear_velocity()
    world.step(render=False)
final_velocity = linear_velocity

print(json.dumps({
    "tutorial": "hello_world_4_5_official",
    "start_z_m": float(start_pos[2]),
    "end_z_m": float(position[2]),
    "delta_z_m": float(start_pos[2] - position[2]),
    "final_linear_velocity": [float(v) for v in final_velocity],
    "frames": 500,
}), flush=True)

simulation_app.close()
