# PyMechanical API surface

PyMechanical = `ansys-mechanical-core`. There are two modes:

- **Remote** (what sim uses): `launch_mechanical()` spawns `AnsysWBU.exe
  -DSApplet` and returns a gRPC client. Has a GUI window. Snippets run
  inside Mechanical's IronPython interpreter.
- **Embedded**: `App()` loads Mechanical.dll in-process. Fast, no GUI,
  no window to screenshot. **sim does not use embedded mode** because
  the observation commands need the GUI on the desktop.

## Launching

```python
import ansys.mechanical.core as pm

mech = pm.launch_mechanical(
    version=241,              # 24.1 = 241; 24.2 = 242; ...
    batch=False,              # MUST be False for sim — GUI required
    cleanup_on_exit=False,    # let sim control teardown
    start_timeout=120,
)
mech.wait_till_mechanical_is_ready(wait_time=120)
```

`launch_mechanical` returns a `Mechanical` client holding the gRPC
channel. Under the hood this is a long-lived connection — reuse it.

## Client methods (sim-relevant)

| Method | Purpose |
|---|---|
| `run_python_script(code)` | Execute snippet in Mechanical's IronPython. Returns the last expression as a string. |
| `run_python_script_from_file(path)` | Same, but from a file on the client side. |
| `exit()` | Close the session. sim's `disconnect` calls this. |
| `verify_valid_connection()` | Health-check the gRPC channel. |
| `wait_till_mechanical_is_ready(wait_time)` | Block until the IronPython interpreter is responsive. **Always call after launch.** |
| `upload(file_name)` | Upload a client file to Mechanical's working dir. |
| `download(files, target_dir)` | Download files from Mechanical's working dir. |
| `list_files()` | List files in the current Mechanical working directory. |
| `download_project(directory, ...)` | Pull the entire project tree. |
| `get_product_info()` | Version / build info as a string. |
| `clear()` | Reset the Mechanical model to an empty state. |

## Running a script

```python
code = '''
analyses = ExtAPI.DataModel.Project.Model.Analyses
result = {"n_analyses": len(analyses), "types": [str(a.AnalysisType) for a in analyses]}
import json
json.dumps(result)
'''
out = mech.run_python_script(code)   # out is a string like '{"n_analyses": 1, ...}'
```

**Important**: the *last expression* of the snippet is what comes back.
If you want structured output, end the snippet with a literal
`json.dumps(...)` — no assignment. The driver will parse the last JSON
line from `stdout` into `result`.

## File transfer pattern

```python
# 1. Upload a .mechdb or .agdb from the client
mech.upload(file_name="C:/work/pipes.mechdb")

# 2. Tell Mechanical to open it
mech.run_python_script('ExtAPI.DataModel.Project.Open("pipes.mechdb")')

# 3. After solve, download the result back
mech.download(files="*.rst", target_dir="C:/work/results")
```

Uploads land in the **Mechanical working directory** (typically
`%TEMP%/AnsysMech<pid>/`). Use `list_files()` to discover the actual
location if unsure.

## Error handling

`run_python_script` re-raises most IronPython exceptions as
`grpc.RpcError`. The driver wraps these in `{"ok": false, "error": ...}`
so sim returns a structured error to the caller instead of a traceback.

Two classes of failure to distinguish:

1. **gRPC channel broken** (Mechanical crashed) — next call will hang.
   `verify_valid_connection()` to detect.
2. **IronPython exception** (`ValueError`, attribute missing) — channel
   is still live; fix the snippet and retry.

## Version matrix

| PyMechanical | Ansys Mechanical |
|---|---|
| 0.11.x | 23.2 – 24.1 |
| 0.12.x | 24.1 – 25.1 |
| 0.13.x | 25.1 – 25.2 |

sim pins `>=0.11,<0.13` for Ansys 24.1 (see `compatibility.yaml`).
