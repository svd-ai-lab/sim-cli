"""omni.* imported before SimulationApp — should lint-warn."""
from omni.isaac.core import World
from isaacsim import SimulationApp
simulation_app = SimulationApp({"headless": True})
simulation_app.close()
