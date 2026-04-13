"""Valid Abaqus/CAE Python script — creates a simple part."""
from abaqus import *
from abaqusConstants import *

model = mdb.Model(name="TestModel")
part = model.Part(name="Block", dimensionality=THREE_D, type=DEFORMABLE_BODY)
print('{"ok": true, "model": "TestModel"}')
