"""Minimal HyperMesh script -- read model and count entities."""
import json
import hm
import hm.entities as ent

model = hm.Model()
nodes = hm.Collection(model, ent.Node)
elems = hm.Collection(model, ent.Element)
print(json.dumps({
    "ok": True,
    "n_nodes": len(nodes),
    "n_elements": len(elems),
}))
