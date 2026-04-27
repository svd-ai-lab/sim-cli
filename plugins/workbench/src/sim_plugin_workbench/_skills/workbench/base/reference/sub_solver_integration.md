# Sub-Solver Integration

> Applies to: PyWorkbench SDK 0.4+ (some methods require 0.10+)

## Overview

Workbench can host multiple analysis systems. PyWorkbench can start
sub-solver gRPC servers for these systems, allowing direct programmatic
control via their respective PyAnsys clients (PyMechanical, PyFluent,
PySherlock).

## Pattern

```
Workbench Session
  └─ Analysis System ("SYS")
      └─ start_<solver>_server("SYS") → port/info
          └─ PyAnsys client connects to port
```

## PyMechanical integration

```python
# 1. Create a Mechanical system in Workbench
wb.run_script_string('''
template1 = GetTemplate(TemplateName="Static Structural", Solver="ANSYS")
system1 = template1.CreateSystem()
''')

# 2. Start PyMechanical server
port = wb.start_mechanical_server(system_name="SYS")

# 3. Connect with PyMechanical
from ansys.mechanical.core import launch_mechanical
mechanical = launch_mechanical(start_instance=False, port=port)

# 4. Use PyMechanical API
mechanical.run_python_script("Model.Mesh.GenerateMesh()")
```

## PyFluent integration

```python
# 1. Create a Fluent system
wb.run_script_string('''
template1 = GetTemplate(TemplateName="Fluent", Solver="FLUENT")
system1 = template1.CreateSystem()
''')

# 2. Start PyFluent server
server_info = wb.start_fluent_server(system_name="SYS")

# 3. Connect with PyFluent
import ansys.fluent.core as pyfluent
fluent = pyfluent.connect_to_fluent(server_info_file_name=server_info)
```

## PySherlock integration (SDK 0.10+ only)

```python
port = wb.start_sherlock_server(system_name="SYS")

from ansys.sherlock.core import pysherlock
sherlock = pysherlock.connect_grpc_channel(port=port)
sherlock.common.check()
```

## Stopping servers (SDK 0.10+ only)

```python
wb.stop_mechanical_server(system_name="SYS")
wb.stop_fluent_server(system_name="SYS")
wb.stop_sherlock_server(system_name="SYS")
```

SDK 0.4-0.9 does not have stop methods. The servers are cleaned up
when the Workbench session terminates.

## Notes

- `system_name` is the Workbench system identifier (e.g., "SYS", "SYS 1")
- The system must exist in the project before starting its server
- Sub-solver licenses are consumed when the server starts
- Only one server per system at a time
