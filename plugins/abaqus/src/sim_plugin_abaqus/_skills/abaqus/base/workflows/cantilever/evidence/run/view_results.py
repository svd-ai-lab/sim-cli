"""Open cantilever.odb in Abaqus/CAE viewer, display deformation, save image.

Run via: abaqus cae noGUI=view_results.py
"""
from abaqus import *
from abaqusConstants import *
import visualization
import os

work_dir = os.getcwd()
odb_path = os.path.join(work_dir, 'cantilever.odb')
evidence_dir = work_dir

# Open ODB
odb = visualization.openOdb(path=odb_path)

# Create viewport
vp = session.viewports['Viewport: 1']
vp.setValues(displayedObject=odb)

# Show deformed shape with U magnitude contour
vp.odbDisplay.display.setValues(plotState=(CONTOURS_ON_DEF,))
vp.odbDisplay.setPrimaryVariable(
    variableLabel='U',
    outputPosition=NODAL,
    refinement=(COMPONENT, 'U2'),
)

# Set white background for clarity
session.graphicsOptions.setValues(backgroundStyle=SOLID, backgroundColor='#FFFFFF')

# Save image
png_path = os.path.join(evidence_dir, 'cantilever_deformation.png')
session.printToFile(
    fileName=png_path,
    format=PNG,
    canvasObjects=(vp,),
)

print("Image saved to:", png_path)
