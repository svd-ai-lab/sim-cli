<!-- Source: https://examples.workbench.docs.pyansys.com/version/stable/examples/cooled-turbine-blade/main.html -->

# Cooled Turbine Blade

This example demonstrates using the Workbench client to upload project files, run scripts, start services, and handle output files. It includes launching PyMechanical to solve models and visualize results.

## Initial Setup

First, import necessary modules for filesystem operations and Ansys services:

```python
import os
import pathlib

from ansys.workbench.core import launch_workbench
from ansys.mechanical.core import connect_to_mechanical
```

## Launch Workbench Service

Define working directories and launch a Workbench session:

```python
workdir = pathlib.Path("__file__").parent

assets = workdir / "assets"
scripts = workdir / "scripts"

wb = launch_workbench(show_gui=True, client_workdir=str(workdir.absolute()))
```

## Upload Project Files

Upload the turbine blade project file to the server:

```python
wb.upload_file_from_example_repo("cooled-turbine-blade/wbpz/cooled_turbine_blade.wbpz")
```

## Execute Workbench Script

Run a Workbench script to define the project and load geometry:

```python
export_path = 'wb_log_file.log'
wb.set_log_file(export_path)
sys_name = wb.run_script_file(str((assets / "project.wbjn").absolute()), log_level='info')
print(sys_name)
```

Output: `SYS`

## Start PyMechanical Server

Create a PyMechanical session connected to the Workbench system:

```python
server_port = wb.start_mechanical_server(system_name=sys_name)

mechanical = connect_to_mechanical(ip='localhost', port=server_port)

print(mechanical.project_directory)
```

## Run Analysis Script

Execute the turbine blade analysis via PyMechanical:

```python
with open(scripts / "cooled_turbine_blade.py") as sf:
    mech_script = sf.read()
mech_output = mechanical.run_python_script(mech_script)
print(mech_output)
```

Output: `{"Stress": "2802182020.5917487 [Pa]"}`

## Retrieve Solver Output

Locate and download solver output files from the server:

```python
mechanical.run_python_script(f"solve_dir=ExtAPI.DataModel.AnalysisList[1].WorkingDir")

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

## Retrieve and Display Results Images

Download and display stress visualization:

```python
from matplotlib import image as mpimg
from matplotlib import pyplot as plt

mechanical.run_python_script(f"image_dir=ExtAPI.DataModel.AnalysisList[1].WorkingDir")

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

image_name = "stress.png"
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

## Copy All Output Files

Transfer all solver files from server to local directory:

```python
import shutil
import glob

current_working_directory = os.getcwd()
target_dir2 = current_working_directory
print(f"Files to be copied from server path at: {target_dir2}")

print(f"All the solver file is stored on the server at: {result_solve_dir_server}")

source_dir = result_solve_dir_server
destination_dir = target_dir2

for file in glob.glob(source_dir + '/*'):
    shutil.copy(file, destination_dir)
```

## Cleanup

Gracefully shut down both services:

```python
mechanical.exit()
wb.exit()
```
