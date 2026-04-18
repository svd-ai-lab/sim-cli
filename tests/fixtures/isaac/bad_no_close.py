"""Missing simulation_app.close() — should lint-warn."""
from isaacsim import SimulationApp
simulation_app = SimulationApp({"headless": True})
print("no close")
