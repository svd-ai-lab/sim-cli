"""Mock script that prints JSON output without needing pybamm."""
import json
import time

time.sleep(0.1)
print(json.dumps({"voltage_V": 3.72, "time_s": 3600}))
