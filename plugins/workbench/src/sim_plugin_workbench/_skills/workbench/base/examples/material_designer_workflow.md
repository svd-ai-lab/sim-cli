<!-- Source: https://examples.workbench.docs.pyansys.com/version/stable/examples/material-designer-workflow/main.html -->

# Material Designer

## Overview

This example demonstrates how to send user-defined parameter values to a parameterized analysis and receive corresponding simulation output via a Workbench service on a local machine.

## Setup and Initialization

```python
import os
import pathlib

from ansys.workbench.core import launch_workbench
```

Launch the Workbench service locally with specified directories. The `workdir` is set to the parent directory of the current file, with `assets`, `scripts`, and `wbpz` as subdirectories.

```python
workdir = pathlib.Path("__file__").parent

assets = workdir / "assets"

wb = launch_workbench(client_workdir=str(workdir.absolute()))
```

## Upload Project Files

Upload the project files to the server using the upload method. The file `MatDesigner.wbpz` is transferred from the example repository.

```python
wb.upload_file_from_example_repo('material-designer-workflow/wbpz/MatDesigner.wbpz')
```

## Execute Project Script

Run a Workbench script to define the project and load geometry. Configure logging output to `wb_log_file.log`.

```python
export_path = 'wb_log_file.log'
wb.set_log_file(export_path)
sys_name = wb.run_script_file(str((assets / "project.wbjn").absolute()), log_level='info')
```

## Modify Material Properties

Prepare a command template to adjust material properties, specifically Young's modulus:

```python
wbjn_template = """designPoint1 = Parameters.GetDesignPoint(Name="0")
parameter1 = Parameters.GetParameter(Name="P1")
designPoint1.SetParameterExpression(
    Parameter=parameter1,
    Expression="{} [Pa]")
backgroundSession1 = UpdateAllDesignPoints(DesignPoints=[designPoint1])
"""
```

Update the project with a new Young's modulus value:

```python
my_command = wbjn_template.format( 1.6e10 )
wb.run_script_string( my_command )
```

## Extract Output Values

Prepare a script to query output parameter values:

```python
extract_output = '''import json
p = Parameters.GetParameter(Name="P{}")
my_tag = p.DisplayText
wb_script_result =json.dumps( my_tag + ',' + str(p.Value) )
'''
```

Retrieve and process updated output values:

```python
outputs = {}
for p in range( 2 , 12 ):
    return_val = wb.run_script_string( extract_output.format( p ) ).split(',')
    name = return_val[0]
    parameter_val = float(return_val[1])
    outputs[ name ] = parameter_val
print( outputs )
```

Output results showing material properties:

```python
{'E1': 3610882.9131690366, 'E2': 3610879.6096576294, 'E3': 799999806.0920515,
 'G12': 898955.9989929767, 'G23': 157509427.7626837, 'G31': 157509427.7626837,
 'nu12': 0.9912444183605882, 'nu13': 0.0013540814399848606,
 'nu23': 0.0013540802011677141, 'rho': 392.499922259344}
```

## Cleanup

Gracefully shut down the Workbench service:

```python
wb.exit()
```
