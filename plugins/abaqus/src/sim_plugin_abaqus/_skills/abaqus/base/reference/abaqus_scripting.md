# Abaqus/CAE Python Scripting Reference

> Applies to: Abaqus 2024-2026
> Last verified: 2026-04-13

## Overview

Abaqus/CAE has an embedded Python interpreter. Scripts use the `abaqus`
and `abaqusConstants` modules. Execution:

```bash
abaqus cae noGUI=script.py     # headless
abaqus cae script=script.py    # with GUI
```

## Key Imports

```python
from abaqus import *
from abaqusConstants import *
from caeModules import *       # for mesh, load, etc.
import visualization           # for ODB post-processing
```

## Object Model Hierarchy

```
session
  └── mdb (Model Database)
        └── models['ModelName']
              ├── parts['PartName']
              │     ├── nodes, elements
              │     ├── sets, surfaces
              │     └── datum planes/axes
              ├── materials['MatName']
              │     └── elastic, density, ...
              ├── sections['SecName']
              ├── rootAssembly
              │     └── instances['InstName']
              ├── steps['StepName']
              ├── loads['LoadName']
              ├── boundaryConditions['BCName']
              └── jobs['JobName']
```

## Common Patterns

### Create a model and part

```python
model = mdb.Model(name='MyModel')
sketch = model.ConstrainedSketch(name='profile', sheetSize=200.0)
sketch.rectangle(point1=(0.0, 0.0), point2=(10.0, 1.0))
part = model.Part(name='Beam', dimensionality=TWO_D_PLANAR,
                  type=DEFORMABLE_BODY)
part.BaseShell(sketch=sketch)
```

### Assign material

```python
material = model.Material(name='Steel')
material.Elastic(table=((200.0E9, 0.3),))
material.Density(table=((7850.0,),))
model.HomogeneousSolidSection(name='BeamSection',
                              material='Steel', thickness=1.0)
region = part.Set(name='AllElements', elements=part.elements)
part.SectionAssignment(region=region, sectionName='BeamSection')
```

### Mesh

```python
part.seedPart(size=0.5, deviationFactor=0.1)
part.generateMesh()
```

### Assembly and step

```python
assembly = model.rootAssembly
instance = assembly.Instance(name='BeamInstance', part=part, dependent=ON)
model.StaticStep(name='Load', previous='Initial')
```

### Boundary conditions and loads

```python
# Fix left edge
region = instance.sets['LeftEdge']
model.DisplacementBC(name='Fixed', createStepName='Load',
                     region=region, u1=0.0, u2=0.0)

# Apply load
region = instance.sets['TipNode']
model.ConcentratedForce(name='TipLoad', createStepName='Load',
                        region=region, cf2=-1000.0)
```

### Submit and monitor

```python
job = mdb.Job(name='MyJob', model='MyModel')
job.submit()
job.waitForCompletion()
```

### Read ODB results

```python
odb = visualization.openOdb(path='MyJob.odb')
step = odb.steps['Load']
frame = step.frames[-1]
displacement = frame.fieldOutputs['U']
for v in displacement.values:
    print(f"Node {v.nodeLabel}: U={v.data}")
odb.close()
```

## Gotchas

- Abaqus Python is CPython 3.x (since Abaqus 2024) but with a custom
  module path — don't assume standard site-packages are available
- `noGUI` mode has no `session.viewports` — visualization calls will fail
- `job.waitForCompletion()` blocks until solver finishes
- Output requests must match field names exactly (case-sensitive)
- On Windows with CJK locale, file paths with non-ASCII chars may cause
  issues — use ASCII paths for job directories
