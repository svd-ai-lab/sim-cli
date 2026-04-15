"""Minimal OpenSeesPy script — 2D truss node setup."""
import json
import openseespy.opensees as ops

ops.wipe()
ops.model('basic', '-ndm', 2, '-ndf', 2)
ops.node(1, 0.0, 0.0)
ops.node(2, 1.0, 0.0)
ops.fix(1, 1, 1)

print(json.dumps({"ok": True, "n2_x": ops.nodeCoord(2)[0]}))
