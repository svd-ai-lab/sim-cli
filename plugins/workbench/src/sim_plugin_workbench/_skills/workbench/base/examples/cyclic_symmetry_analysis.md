<!-- Source: https://examples.workbench.docs.pyansys.com/version/stable/examples/cyclic-symmetry-analysis/main.html -->

# Cyclic Symmetry Analysis

## Overview

This example demonstrates how to use the Workbench client to manage projects on a remote host, run scripts, and handle output files. It covers launching services, uploading files, executing scripts, and visualizing results using PyMechanical.

## Setup and Imports

```python
import os
import pathlib

from ansys.workbench.core import launch_workbench
from ansys.mechanical.core import connect_to_mechanical
```

## Directory Configuration

Launch the Workbench service on a remote host machine, specifying the remote host machine name and user login credentials. Define several directories that will be used during the session. `workdir` is set to the parent directory of the current file. `assets`, `scripts`, and `cdb` are subdirectories within the working directory.

```python
workdir = pathlib.Path("__file__").parent

assets = workdir / "assets"
scripts = workdir / "scripts"

wb = launch_workbench(client_workdir=str(workdir.absolute()))
```

## Uploading Project Files

Upload the project files to the server using the `upload_file_from_example_repo` method. The file to upload is `sector_model.cdb`.

```python
wb.upload_file_from_example_repo("cyclic-symmetry-analysis/cdb/sector_model.cdb")
```

Output: `Uploading sector_model.cdb: 100%|----------| 7.86M/7.86M [00:00<00:00, 87.9MB/s]`

## Project Setup and Mechanical Server

Execute a Workbench script (`project.wbjn`) to define the project and load the geometry using the `run_script_file` method. The `set_log_file` method directs logs to `wb_log_file.log`. The name of the system created is stored in `sys_name` and printed.

```python
export_path = 'wb_log_file.log'
wb.set_log_file(export_path)
sys_name = wb.run_script_file(str((assets / "project.wbjn").absolute()), log_level='info')
print(sys_name)
```

Output: `SYS 1`

Start a PyMechanical server for the system using the `start_mechanical_server` method. Create a PyMechanical client session connected to this server using `connect_to_mechanical`. The project directory is printed to verify the connection.

```python
server_port = wb.start_mechanical_server(system_name=sys_name)

mechanical = connect_to_mechanical(ip='localhost', port=server_port)

print(mechanical.project_directory)
```

Output: `C:\Users\ansys\AppData\Local\Temp\WB_ansys_19576_2\wbnew_files\`

## Analysis Execution

Read and execute the script `cyclic_symmetry_analysis.py` via the PyMechanical client using `run_python_script`. This script typically contains commands to mesh and solve the model.

```python
with open(scripts / "cyclic_symmetry_analysis.py") as sf:
    mech_script = sf.read()
mech_output = mechanical.run_python_script(mech_script)
print(mech_output)
```

Output: `{"Total Deformation": "5.202362674608513 [mm]", "Total Deformation 2": "2.182211520602412 [mm]"}`

## Solver Output Retrieval

Specify the Mechanical directory and run a script to fetch the working directory path. Download the solver output file (`solve.out`) from the server to the client's current working directory and print its contents.

```python
mechanical.run_python_script(f"solve_dir=ExtAPI.DataModel.AnalysisList[5].WorkingDir")
result_solve_dir_server = mechanical.run_python_script(f"solve_dir")
print(f"All solver files are stored on the server at: {result_solve_dir_server}")
```

```python
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

The solver output displays ANSYS MAPDL run statistics, including:
- Harmonic response analysis setup with 20 substeps
- Frequency range from 1200 Hz to 5500 Hz
- Cyclic symmetry sector angle of 27.692 degrees
- Constraint equations: 6669
- Total nodes: 40,644 and elements: 26,169
- Solution time: 226.2 seconds

## Visualization and Results Download

Download and display the deformation result image using matplotlib:

```python
from matplotlib import image as mpimg
from matplotlib import pyplot as plt

mechanical.run_python_script(f"image_dir=ExtAPI.DataModel.AnalysisList[5].WorkingDir")
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

image_name = "deformation.png"
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

## Complete Results Download

Download all the files from the server to the current working directory:

```python
mechanical.run_python_script(f"solve_dir=ExtAPI.DataModel.AnalysisList[5].WorkingDir")
result_solve_dir_server = mechanical.run_python_script(f"solve_dir")
print(f"All solver files are stored on the server at: {result_solve_dir_server}")

solve_out_path = os.path.join(result_solve_dir_server, "*.*")

current_working_directory = os.getcwd()
mechanical.download(solve_out_path, target_dir=current_working_directory)
```

Downloaded files include: CAERep.xml, CAERepOutput.xml, cyclic_map.json, deformation.png, ds.dat, file.aapresults, file.rst, file0.err, MatML.xml, solve.out.

## Cleanup

Gracefully shut down both services:

```python
mechanical.exit()
wb.exit()
```
