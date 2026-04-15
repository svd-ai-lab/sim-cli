"""Minimal SfePy script — generate a block mesh and report cell count."""
import json
from sfepy.mesh.mesh_generators import gen_block_mesh

mesh = gen_block_mesh([1.0, 1.0], [5, 5], [0.5, 0.5], name='block')
print(json.dumps({"ok": True, "n_cells": int(mesh.n_el)}))
