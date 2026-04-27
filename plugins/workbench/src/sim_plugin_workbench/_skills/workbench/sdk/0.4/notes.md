# SDK 0.4 Notes

> Version: ansys-workbench-core 0.4.x–0.9.x
> Applies to: Ansys 24.1 (v241)

## What's different from 0.10+

### Parameter naming

```python
# SDK 0.4: uses 'release' parameter
wb = pywb.launch_workbench(release="241")

# SDK 0.10+: uses 'version' parameter
wb = pywb.launch_workbench(version="242")
```

### Missing methods

These methods do NOT exist in SDK 0.4:

- `download_project_archive()` — added in 0.10
- `stop_mechanical_server()` — added in 0.10
- `stop_fluent_server()` — added in 0.10
- `stop_sherlock_server()` — added in 0.10
- `start_sherlock_server()` — added in 0.10

### Missing features

- No `show_gui` parameter on `launch_workbench()` (GUI always shows)
- No `server_version` property on client
- `run_script_file()` does not support `args` parameter

### Why use this version

SDK 0.10+ hardcodes `int(version) < 242` and refuses to connect to
Ansys 24.1. SDK 0.4-0.9 has no such restriction.
