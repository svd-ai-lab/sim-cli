"""Minimal trimesh script — box volume."""
import json
import trimesh
m = trimesh.creation.box(extents=[2, 3, 4])
print(json.dumps({"ok": True, "volume": m.volume}))
