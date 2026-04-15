"""Minimal Devito script — grid + TimeFunction."""
import json
from devito import Grid, TimeFunction
g = Grid(shape=(10, 10), extent=(1.0, 1.0))
u = TimeFunction(name='u', grid=g, time_order=1, space_order=2)
print(json.dumps({"ok": True, "shape": list(u.shape)}))
