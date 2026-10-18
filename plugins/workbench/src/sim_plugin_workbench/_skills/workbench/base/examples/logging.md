<!-- Source: https://examples.workbench.docs.pyansys.com/version/stable/examples/logging/main.html -->

# Logging

This example showcases the logging capabilities of PyWorkbench.

## Initial Setup

First, import the necessary modules. The example uses `pathlib` for handling filesystem paths and `os` for operating system interactions. The `launch_workbench` function from `ansys.workbench.core` is imported to start a Workbench session.

```python
import pathlib
import os
from ansys.workbench.core import launch_workbench
```

## Directory Configuration

Next, define several directories that will be used during the session. The `workdir` is set to the directory containing the current file, with `server_workdir`, `client_workdir`, and `alternative_target_dir` as subdirectories within the working directory.

```python
workdir = pathlib.Path("__file__").parent
server_workdir = workdir / "server_workdir"
client_workdir = workdir / "client_workdir"
alternative_target_dir = workdir / "alternative_target_dir"
```

## Launching Workbench

The `launch_workbench` function starts a Workbench session with absolute paths to avoid ambiguity in directory locations.

```python
wb = launch_workbench(server_workdir=str(server_workdir.absolute()), client_workdir=str(client_workdir.absolute()))
```

## File Download Operations

Download files from the server using wildcard patterns. The `download_file` method fetches all files matching the specified pattern.

```python
downloaded1 = wb.download_file('server1.*')
```

Download the entire server directory contents to an alternative local directory.

```python
downloaded2 = wb.download_file('*', target_dir=alternative_target_dir)
```

## File Upload Operations

Upload files to the server using wildcard patterns. All `.txt` files and files matching the pattern `model?.prt` in the client directory are uploaded.

```python
wb.upload_file('*.txt', 'model?.prt')
```

Upload files from an alternative directory with non-existing files specified. The `show_progress` parameter disables the progress bar during upload.

```python
wb.upload_file(os.path.join(alternative_target_dir, 'app.py'), 'non_existing_file1', 'non_existing_file2', show_progress=False)
```

## Logging Configuration with File Output

Set up a log file for script execution. The `set_log_file` method directs logs to the specified file, and `run_script_file` executes a script with a specific log level.

```python
export_path = 'wb_log_file.log'
wb.set_log_file(export_path)
print(wb.run_script_file('wb.wbjn', log_level='info'))
```

## Console Logging Configuration

Disable the log file using `reset_log_file`, then set the console log level to `info`.

```python
wb.reset_log_file()
wb.set_console_log_level('info')
print(wb.run_script_file('wb.wbjn', log_level='info'))
```

Adjust the console log level to `error` for more restrictive logging.

```python
wb.set_console_log_level('error')
print(wb.run_script_file('wb.wbjn', log_level='info'))
```

## Session Cleanup

Close the Workbench session.

```python
wb.exit()
```
