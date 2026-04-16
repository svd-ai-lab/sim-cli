"""HyperMesh script using interactive selection -- fails in batch."""
import hm
import hm.entities as ent

model = hm.Model()
elems = hm.CollectionByInteractiveSelection(model, ent.Element)
print(len(elems))
