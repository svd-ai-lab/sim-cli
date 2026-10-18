# File Transfer Patterns

> Applies to: PyWorkbench SDK (all versions)

## Overview

PyWorkbench operates in a client-server model. Files must be explicitly
transferred between the client machine and the Workbench server. The
server has its own working directory where uploaded files land and from
which downloaded files are served.

## Upload

```python
# Single file
wb.upload_file("geometry.scdoc")

# Multiple files
wb.upload_file("mesh.msh", "setup.jou", "solve.jou")

# Wildcard
wb.upload_file("*.agdb")

# Without progress bar
wb.upload_file("large_model.scdoc", show_progress=False)
```

## Download

```python
# Single file
local_path = wb.download_file("results.csv")

# To specific directory
wb.download_file("output.txt", target_dir="C:/results")

# Wildcard (returns .zip if multiple matches)
archive = wb.download_file("*.dat")
```

## Project archive (SDK 0.10+ only)

```python
# Download entire project as .wbpz
wb.download_project_archive(
    "project.wbpz",
    include_solution_result_files=True,
)
```

## From example repository

```python
# Download from ansys/example-data GitHub repo
wb.upload_file_from_example_repo("pyworkbench/mixing_elbow.scdoc")
```

## Common workflow: geometry import

```python
# 1. Upload geometry to server
wb.upload_file("part.agdb")

# 2. Import via IronPython journal
journal = '''
geometry1 = system1.GetContainer(ComponentName="Geometry")
geometry1.SetFile(FilePath="part.agdb")
'''
wb.run_script_string(journal)
```

## Working directories

- **Client workdir**: Set via `client_workdir` parameter in `launch_workbench()`.
  Defaults to system temp dir. Uploaded files are read from here.
- **Server workdir**: Set via `server_workdir` parameter. Defaults to
  Workbench preference. Uploaded files land here. Journal scripts can
  access files by name (relative to server workdir).
