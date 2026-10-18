# SDK 0.10 Notes

> Version: ansys-workbench-core 0.10+
> Applies to: Ansys 24.2+ (v242, v251, v252)

## What's new vs 0.4

### New methods

- `download_project_archive(archive_name, include_solution_result_files=True)`
  — Download entire project as `.wbpz` archive.
- `stop_mechanical_server(system_name)` — Explicitly stop PyMechanical server.
- `stop_fluent_server(system_name)` — Explicitly stop PyFluent server.
- `start_sherlock_server(system_name)` / `stop_sherlock_server(system_name)`
  — PySherlock integration.

### Parameter changes

```python
# SDK 0.10+: 'version' parameter (was 'release' in 0.4)
wb = pywb.launch_workbench(version="242", show_gui=False)
```

- `show_gui` parameter added (defaults to `True`)
- `use_insecure_connection` parameter added
- `run_script_file()` supports `args` parameter

### Version gate

SDK 0.10+ validates version:
```python
if int(version) < 242:
    raise Exception("Invalid Ansys version: " + version)
```

This means Ansys 24.1 **cannot** use SDK 0.10+.

### ReturnValue support

On SDK 0.10+, IronPython scripts can use `ReturnValue()` to pass data
back through `run_script_string()`:

```python
# In IronPython journal:
ReturnValue("some result string")
```

This is NOT available on SDK 0.4 or Ansys 24.1.
