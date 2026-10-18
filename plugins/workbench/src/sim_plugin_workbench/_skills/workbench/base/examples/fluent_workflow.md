<!-- Source: https://examples.workbench.docs.pyansys.com/version/stable/examples/ansys-fluent-workflow/main.html -->

# Ansys Fluent Workflow

## Overview

This example demonstrates PyWorkbench, a Python client scripting tool for Ansys Workbench, applied to an Ansys Fluent workflow. The demonstration utilizes Fluent TUI (Text User Interface) journal files for simulation setup and solving, along with Ansys Fluent Meshing WTM (Water Tight Meshing Workflow) capabilities through recorded journaling.

The tutorial illustrates how Workbench's journaling feature—which records user interface actions as Python scripts—can automate repetitive analyses and enable batch processing. This example shows how to use such journal files with PyWorkbench for Fluent workflows.

## Problem Description

The example models three-dimensional turbulent fluid flow and heat transfer in a mixing elbow (common in industrial piping). Cold fluid at 20°C enters through a large inlet and mixes with warmer fluid at 40°C from a smaller elbow inlet. With Reynolds number of 50,800 at the larger inlet, turbulent flow modeling is necessary. This configuration is typical for power plants and process industries.

## Tutorial Coverage

This use case demonstrates several PyWorkbench capabilities:

- Initiating an Ansys Workbench server locally and establishing client connection
- Uploading input data from client to server working directories
- Executing Ansys Workbench journal scripts that run Fluent simulations
- Downloading results from server to client
- Shutting down the server

## Code Implementation

### Required Imports

```python
import pathlib
from ansys.workbench.core import launch_workbench
```

### Setting Up Working Directories and Asset Paths

```python
workdir = pathlib.Path("__file__").parent

server_workdir = workdir / 'server_workdir'
server_workdir.mkdir(exist_ok=True)

assets = workdir / "assets"
scdoc = assets / "scdoc"
jou = assets / "jou"
```

### Launching the Workbench Session

```python
wb = launch_workbench(server_workdir=str(server_workdir.absolute()), client_workdir=str(workdir.absolute()))
```

### Uploading Input Data

```python
wb.upload_file(str(scdoc / "mixing_elbow.scdoc"))
wb.upload_file(str(jou / "setup.jou"))
wb.upload_file(str(jou / "solve.jou"))
```

### Executing a Workbench Script

```python
sys_name = wb.run_script_file(str((assets / "project.wbjn").absolute()))
```

### Downloading Output Files

```python
wb.download_file("temperature_contour.jpeg")
```

### Shutting Down the Server

```python
wb.exit()
```
