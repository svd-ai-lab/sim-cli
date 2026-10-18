# Workbench Journal Scripting (.wbjn)

> Source: Ansys Workbench Scripting Guide + practical testing
> Language: IronPython 2.7 (.NET Framework 4.x)
> File extension: `.wbjn`

## Overview

Workbench journals are IronPython scripts executed inside the Workbench
process. They access the Workbench data model directly through global
functions and objects. Journals can be recorded from the GUI
(File > Scripting > Record Journal) and played back.

## Core API

### Version gate

```python
SetScriptVersion(Version="24.1")   # Must match installed Workbench version
```

### Create analysis systems

```python
# Get a system template
template1 = GetTemplate(TemplateName="Static Structural", Solver="ANSYS")

# Create the system in the project schematic
system1 = template1.CreateSystem()
```

### Access system components

```python
# Standard components in a Static Structural system:
engData   = system1.GetContainer(ComponentName="Engineering Data")
geometry  = system1.GetContainer(ComponentName="Geometry")
model     = system1.GetContainer(ComponentName="Model")
setup     = system1.GetContainer(ComponentName="Setup")
solution  = system1.GetContainer(ComponentName="Solution")
results   = system1.GetContainer(ComponentName="Results")
```

### Edit geometry

```python
geometry1 = system1.GetContainer(ComponentName="Geometry")
geometry1.SetFile(FilePath="C:/models/part.agdb")
# or
geometry1.Edit()  # Opens SpaceClaim/DesignModeler
```

### Update/Solve

```python
model1 = system1.GetModel()
model1.Solve()        # Run the solver
```

### Save project

```python
Save(Overwrite=True)
SaveAs(FilePath="C:/projects/myproject.wbpj")
```

### Parameters

```python
# Get input parameter
param1 = Parameters.GetParameter(Name="P1")
param1.Expression = "10 [mm]"

# Get output parameter
param2 = Parameters.GetParameter(Name="P2")
value = param2.Value
```

## Result file convention

IronPython stdout is not piped through PyWorkbench. To pass structured
results back to the sim driver, write JSON to a known file:

```python
import json, os, codecs

result = {"ok": True, "step": "create-system", "component_count": 6}

out = os.path.join(os.environ.get("TEMP", "C:\\Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps(result))
f.close()
```

The driver reads this file after `run_script_string()` completes and
appends its content to stdout for `parse_output()` to extract.

## IronPython limitations

- Based on Python 2.7 syntax (no f-strings, no walrus operator)
- `.NET` types may appear (use `str()` to convert)
- `print()` output goes to Workbench log, not to PyWorkbench client
- Use `codecs.open()` instead of `open()` for reliable UTF-8 encoding
- Some Python 3 stdlib modules unavailable (e.g., `pathlib`)
