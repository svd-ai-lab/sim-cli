<!-- Source: https://examples.workbench.docs.pyansys.com/version/stable/examples/axisymmetric-rotor/main.html -->

# Axisymmetric Rotor

## Overview

This example demonstrates running a Workbench service locally to solve both 2D general axisymmetric rotor and 3D rotor models using PyMechanical. The workflow includes uploading project files, executing scripts, downloading results, and displaying output images.

## Setup

Import required modules:

```python
import os
import pathlib

from ansys.workbench.core import launch_workbench
from ansys.mechanical.core import connect_to_mechanical
```

## Launch Workbench Service

Establish a local Workbench session with a specified working directory:

```python
workdir = pathlib.Path("__file__").parent

assets = workdir / "assets"
scripts = workdir / "scripts"

wb = launch_workbench(client_workdir=str(workdir.absolute()))
```

## Upload Project Files

Transfer the geometry database files to the server:

```python
wb.upload_file_from_example_repo("axisymmetric-rotor/agdb/axisymmetric_model.agdb")
wb.upload_file_from_example_repo("axisymmetric-rotor/agdb/rotor_3d_model.agdb")
```

## Execute Workbench Script

Run the project definition script and retrieve system names:

```python
export_path = 'wb_log_file.log'
wb.set_log_file(export_path)
sys_name = wb.run_script_file(str((assets / "project.wbjn").absolute()), log_level='info')
print(sys_name)
```

Output: `['SYS', 'SYS 4']`

## Connect to PyMechanical

Start a PyMechanical server and establish a client session:

```python
server_port = wb.start_mechanical_server(system_name=sys_name[1])

mechanical = connect_to_mechanical(ip='localhost', port=server_port)

print(mechanical.project_directory)
```

## Execute Analysis Script

Run the axisymmetric rotor analysis:

```python
with open(scripts / "axisymmetric_rotor.py") as sf:
    mech_script = sf.read()
mech_output = mechanical.run_python_script(mech_script)
print(mech_output)
```

Output: `{"Total Deformation": "0.79262294403210676 [mm]", "Total Deformation 2": "0.93934788182426 [mm]"}`

## Download Solver Results

Retrieve and display solver output from the Modal Campbell Analysis:

```python
mechanical.run_python_script(f"solve_dir=ExtAPI.DataModel.AnalysisList[2].WorkingDir")
result_solve_dir_server = mechanical.run_python_script(f"solve_dir")
print(f"All solver files are stored on the server at: {result_solve_dir_server}")

solve_out_path = os.path.join(result_solve_dir_server, "solve.out")

def write_file_contents_to_console(path):
    """Write file contents to console."""
    with open(path, "rt") as file:
        for line in file:
            print(line, end="")

current_working_directory = os.getcwd()
mechanical.download(solve_out_path, target_dir=current_working_directory)
solve_out_local_path = os.path.join(current_working_directory, "solve.out")
write_file_contents_to_console(solve_out_local_path)
os.remove(solve_out_local_path)
```

## Download and Display Results Image

Retrieve deformation visualization from the server:

```python
from matplotlib import image as mpimg
from matplotlib import pyplot as plt

mechanical.run_python_script(f"image_dir=ExtAPI.DataModel.AnalysisList[2].WorkingDir")
result_image_dir_server = mechanical.run_python_script(f"image_dir")
print(f"Images are stored on the server at: {result_image_dir_server}")

def get_image_path(image_name):
    return os.path.join(result_image_dir_server, image_name)

def display_image(path):
    print(f"Printing {path} using matplotlib")
    image1 = mpimg.imread(path)
    plt.figure(figsize=(15, 15))
    plt.axis("off")
    plt.imshow(image1)
    plt.show()

image_name = "tot_deform_2D.png"
image_path_server = get_image_path(image_name)

if image_path_server != "":
    current_working_directory = os.getcwd()
    local_file_path_list = mechanical.download(
        image_path_server, target_dir=current_working_directory
    )
    image_local_path = local_file_path_list[0]
    print(f"Local image path : {image_local_path}")
    display_image(image_local_path)
```

## Key Capabilities Demonstrated

- Launching and configuring Workbench services remotely
- Uploading geometry and project files
- Executing mechanical analysis via PyMechanical
- Retrieving solver outputs and visualization results
- Performing modal and unbalance response analyses on rotating machinery

## Cleanup

Gracefully shut down both services:

```python
mechanical.exit()
wb.exit()
```
