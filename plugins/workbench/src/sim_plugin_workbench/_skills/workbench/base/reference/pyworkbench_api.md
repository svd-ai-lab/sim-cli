# PyWorkbench SDK API Reference

> Source: https://workbench.docs.pyansys.com/ + installed SDK 0.4.0
> Package: `pip install ansys-workbench-core`
> Supported Ansys: 24.1+ (SDK 0.4-0.9) / 24.2+ (SDK 0.10+)

## Overview

PyWorkbench (`ansys-workbench-core`) is a Python client that communicates
with an Ansys Workbench server over gRPC. It launches or connects to a
Workbench process and lets you execute IronPython scripts, transfer files,
and start sub-solver services (PyMechanical, PyFluent, PySherlock).

## Connection

### Launch new server

```python
import ansys.workbench.core as pywb

# SDK 0.4.x: uses 'release' parameter
wb = pywb.launch_workbench(release="241")

# SDK 0.10+: uses 'version' parameter, show_gui option
wb = pywb.launch_workbench(version="242", show_gui=False)
```

### Connect to existing server

```python
wb = pywb.connect_workbench(port=32588, host="localhost")
```

## Script Execution

### run_script_string(script_string, log_level="error")

Execute an IronPython script provided as a string.

```python
result = wb.run_script_string('''
SetScriptVersion(Version="24.1")
template1 = GetTemplate(TemplateName="Static Structural", Solver="ANSYS")
system1 = template1.CreateSystem()
''', log_level="warning")
```

- `log_level`: "critical", "debug", "error", "info", "warning"
- Returns: script output as string, or `None` on error

### run_script_file(script_file_name, log_level="error")

Execute a `.wbjn` file from the client working directory.

```python
wb.upload_file("setup.wbjn")
result = wb.run_script_file("setup.wbjn", log_level="warning")
```

## File Transfer

### upload_file(*file_list, show_progress=True)

Upload files from client to server. Supports wildcards.

```python
wb.upload_file("geometry.scdoc")
wb.upload_file("*.agdb", show_progress=False)
```

### download_file(file_name, show_progress=True, target_dir=None)

Download files from server to client.

```python
local_path = wb.download_file("results.csv")
wb.download_file("*.dat", target_dir="/tmp/results")
```

### download_project_archive (SDK 0.10+ only)

```python
wb.download_project_archive("project.wbpz", include_solution_result_files=True)
```

## Sub-Solver Integration

### start_mechanical_server(system_name) → int

Start a PyMechanical gRPC server for a Workbench system.

```python
port = wb.start_mechanical_server(system_name="SYS")
# Connect with PyMechanical:
# from ansys.mechanical.core import launch_mechanical
# mechanical = launch_mechanical(start_instance=False, port=port)
```

### start_fluent_server(system_name) → str

Start a PyFluent server. Returns path to server info file.

```python
server_info = wb.start_fluent_server(system_name="SYS")
# Connect with PyFluent:
# import ansys.fluent.core as pyfluent
# fluent = pyfluent.connect_to_fluent(server_info_file_name=server_info)
```

### start_sherlock_server(system_name) → int

Start a PySherlock gRPC server (SDK 0.10+ only).

## Logging

```python
wb.set_console_log_level("info")     # Change console verbosity
wb.set_log_file("workbench.log")     # Enable file logging
wb.reset_log_file()                  # Disable file logging
```

## Gotchas

1. **SDK 0.10+ rejects Ansys 24.1**: Hardcoded `int(version) < 242` check. Use SDK 0.4-0.9 for 24.1.
2. **Parameter name changed**: SDK 0.4 uses `release="241"`, SDK 0.10+ uses `version="242"`.
3. **IronPython stdout not piped**: `run_script_string()` returns IronPython's `ReturnValue()` output (SDK 0.10+) or `{}` (SDK 0.4). Use file-based result convention.
4. **Working directories matter**: Uploaded files go to server workdir. Use `client_workdir` param to control local paths.
