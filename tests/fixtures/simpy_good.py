"""Minimal SimPy script — env + simple process."""
import json
import simpy
env = simpy.Environment()
def proc(env):
    yield env.timeout(5)
env.process(proc(env))
env.run(until=10)
print(json.dumps({"ok": True, "now": env.now}))
