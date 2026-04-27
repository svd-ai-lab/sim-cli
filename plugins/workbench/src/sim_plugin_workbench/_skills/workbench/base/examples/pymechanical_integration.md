<!-- Source: https://examples.workbench.docs.pyansys.com/version/stable/examples/pymechanical-integration/main.html -->

# PyMechanical Integration

## Overview

This example demonstrates how to use PyWorkbench and PyMechanical together to upload geometry, run simulations, and visualize results. It covers launching services, running scripts, and handling files between the client and server.

## Initial Setup

First, import the necessary modules. The `pathlib` module handles filesystem paths, `os` interacts with the operating system, and `pyvista` provides visualization capabilities. The `launch_workbench` function from `ansys.workbench.core` starts a Workbench session, and `connect_to_mechanical` from `ansys.mechanical.core` initiates a Mechanical session.

```python
import os
import pathlib
import pyvista as pv

from ansys.workbench.core import launch_workbench
from ansys.mechanical.core import connect_to_mechanical
```

## Directory Configuration

Define several directories for use during the session. The `workdir` is set to the parent directory of the current file. `assets`, `scripts`, and `agdb` are subdirectories within the working directory. The `launch_workbench` function initiates a Workbench session with specified directories.

```python
workdir = pathlib.Path("__file__").parent
assets = workdir / "assets"
scripts = workdir / "scripts"
agdb = workdir / "agdb"

wb = launch_workbench(client_workdir=str(workdir.absolute()))
```

## Uploading Geometry

Upload a geometry file (`two_pipes.agdb`) from the example database to the server using the `upload_file_from_example_repo` method.

```python
wb.upload_file_from_example_repo("pymechanical-integration/agdb/two_pipes.agdb")
```

Output:
```
Uploading two_pipes.agdb: 100%|██████████| 2.27M/2.27M [00:00<00:00, 50.8MB/s]
```

## Creating Mechanical System

Execute a Workbench script (`project.wbjn`) to create a mechanical system and load the geometry using the `run_script_file` method. The name of the system created is stored in `system_name`.

```python
system_name = wb.run_script_file(str((assets / "project.wbjn").absolute()))
```

## Starting PyMechanical Service

Start a PyMechanical service for the specified system using the `start_mechanical_server` method. Create a PyMechanical client connected to this service using `connect_to_mechanical` method.

```python
pymech_port = wb.start_mechanical_server(system_name=system_name)

mechanical = connect_to_mechanical(ip='localhost', port=pymech_port)
print(mechanical.project_directory)
```

Output:
```
C:\Users\ansys\AppData\Local\Temp\WB_ansys_8664_2\wbnew_files\
```

## Running Solver Script

Read and execute the script `solve.py` via the PyMechanical client using `run_python_script`. This script typically contains commands to mesh and solve the model.

```python
with open(scripts / "solve.py") as sf:
    mech_script = sf.read()
print(mechanical.run_python_script(mech_script))
```

Output:
```json
{"total_deformation": "1.9647094770595032E-06 [mm]"}
```

## Downloading Results

Fetch output files (`*solve.out` and `*deformation.png`) from the solver directory to the client's working directory using the `download` method.

```python
mechanical.download("*solve.out", target_dir=str(workdir.absolute()))
mechanical.download("*deformation.png", target_dir=str(workdir.absolute()))
```

## Viewing Solver Output

Read and print the content of the solver output file (`solve.out`) to the console.

```python
with open(os.path.join(str(workdir.absolute()), "solve.out"), "r") as f:
    print(f.read())
```

This displays detailed ANSYS MAPDL statistics and analysis information from the finite element analysis run.

## Visualizing Results

Plot the deformation result (`deformation.png`) using `pyvista`. A `Plotter` object is created, and the image is added as a background before displaying.

```python
pl = pv.Plotter()
pl.add_background_image(os.path.join(str(workdir.absolute()), "deformation.png"))
pl.show()
```

## Cleanup

Finally, call the `exit` method on both the PyMechanical and Workbench clients to gracefully shut down the services and release all resources.

```python
mechanical.exit()
wb.exit()
```
