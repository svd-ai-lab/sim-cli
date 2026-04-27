# Known Issues

## SDK 0.10+ rejects Ansys 24.1

**Discovered**: 2026-04-10
**Status**: Workaround available
**Affects**: SDK >= 0.10, Solver 24.1
**Description**: `ansys-workbench-core` 0.10+ hardcodes `int(version) < 242`
check in `workbench_launcher.py:122`, refusing to connect to Ansys 24.1.
**Workaround**: Pin SDK to `ansys-workbench-core>=0.4,<0.10` for Ansys 24.1.

## IronPython stdout not piped

**Discovered**: 2026-04-10
**Status**: Workaround available
**Affects**: All SDK versions, all solver versions
**Description**: `run_script_string()` does not capture IronPython `print()`
output. On SDK 0.4, it returns `{}` or `None`. On SDK 0.10+, it returns
`ReturnValue()` output.
**Workaround**: Write results to `%TEMP%/sim_wb_result.json` using
`codecs.open()`. The driver reads this file automatically.

## Fluent template name is "FLUENT" not "Fluent" on 24.1

**Discovered**: 2026-04-10
**Status**: Documented (skill issue)
**Affects**: Solver 24.1 (possibly locale-dependent)
**Category**: Skill
**Description**: Official PyWorkbench examples use
`GetTemplate(TemplateName="Fluent", Solver="FLUENT")`, but on Ansys 24.1
(Chinese locale) the template is registered as `"FLUENT"` without a Solver
parameter: `GetTemplate(TemplateName="FLUENT")`.
**Workaround**: Use `"FLUENT"` as template name. Other affected templates:
`"Fluid Flow (CFX)"` works, `"CFX"` works, `"Fluid Flow"` works.

## Fluent system only exposes Setup and Solution via GetContainer

**Discovered**: 2026-04-10
**Status**: Documented (skill issue)
**Affects**: Solver 24.1
**Category**: Skill
**Description**: Fluent analysis systems only expose "Setup" and "Solution"
through `system.GetContainer(ComponentName=...)`. Geometry, Mesh, and Results
are managed through the Fluent solver directly, not through Workbench's
component API. This differs from Mechanical systems which expose all 6
components.
**Workaround**: Don't check for Geometry/Mesh/Results components on Fluent
systems. Use the Fluent solver API for mesh and result operations.

## Uploaded files land in %TEMP%, not os.getcwd()

**Discovered**: 2026-04-10
**Status**: Documented (skill issue)
**Affects**: All SDK versions, all solver versions
**Category**: Skill
**Description**: Files uploaded via `wb.upload_file()` land in the server's
TEMP directory (`C:\Users\<user>\AppData\Local\Temp`), not in the IronPython
process's `os.getcwd()` (which is `c:\windows\system32\spool\drivers\x64\3`).
IronPython scripts must use `os.environ.get("TEMP")` as base path to find
uploaded files.
**Workaround**: Always use full path:
```python
import os
path = os.path.join(os.environ.get("TEMP", "C:/Temp"), "filename.txt")
```

## upload_file_from_example_repo downloads HTML instead of binary

**Discovered**: 2026-04-11
**Status**: Workaround available
**Affects**: SDK 0.4
**Category**: Driver (SDK bug)
**Description**: `wb.upload_file_from_example_repo()` may download the
GitHub HTML page instead of the raw binary file when using SDK 0.4.
Verification: check file header — HTML starts with `<`, real .agdb starts
with `\x89HDF`.
**Workaround**: Download the raw file directly via `requests.get()` from
`https://github.com/ansys/example-data/raw/master/pyworkbench/<path>`,
then use `wb.upload_file()`.

## SetFile requires absolute path (server CWD differs from upload dir)

**Discovered**: 2026-04-11
**Status**: Workaround available
**Affects**: All SDK versions, all solver versions
**Category**: Driver + Skill
**Description**: `geometry.SetFile(FilePath="file.agdb")` resolves relative
paths against the Workbench server's CWD (`c:\windows\system32\...`), not
the upload directory (`%TEMP%`). Uploaded files are in `%TEMP%` but
`SetFile` can't find them.
**Workaround**: Use absolute path in IronPython journal:
```python
import os
geo_path = os.path.join(os.environ.get("TEMP","C:/Temp"), "file.agdb")
geometry1.SetFile(FilePath=geo_path)
```

## Mechanical BCs require face-level scoping (not body-level)

**Discovered**: 2026-04-11
**Status**: Known limitation
**Affects**: All versions
**Category**: Skill
**Description**: `AddFixedSupport()` and `AddPressure()` require
`ISelectionInfo` scoped to specific faces, not bodies. Body-level
assignment results in `UnderDefined` state and `Solve()` returns
`SolveRequired` without executing. The official examples use pre-built
scripts (`solve.py`) that handle scoping via ExtAPI.
**Workaround**: Use `ExtAPI.SelectionManager.CreateSelectionInfo()` with
face IDs, or use pre-recorded scripts for specific geometries.

## Model.Mesh.Nodes is int, not collection (Mechanical 241)

**Discovered**: 2026-04-11
**Status**: Documented
**Affects**: Mechanical 241 (may differ in newer versions)
**Category**: Skill
**Description**: `Model.Mesh.Nodes` returns an `int` directly (e.g., 4879),
not a collection with `.Count`. Same for `Model.Mesh.Elements`. Do NOT call
`.Count` on these properties.
**Workaround**: Use `str(Model.Mesh.Nodes)` directly instead of
`str(Model.Mesh.Nodes.Count)`.

## PyMechanical gRPC fails on Chinese-locale strings

**Discovered**: 2026-04-11
**Status**: Known limitation
**Affects**: PyMechanical + Chinese locale
**Category**: Driver (PyMechanical SDK)
**Description**: `run_python_script()` fails with
`'ascii' codec can't decode byte 0` when the IronPython result contains
Chinese characters (e.g., body names in Chinese Ansys). Returning pure
ASCII strings works fine.
**Workaround**: Avoid returning `.Name` or `.DisplayText` of objects that
may contain Chinese text. Use indices or type names instead.

## IronPython UnicodeEncodeError on system names

**Discovered**: 2026-04-10
**Status**: Workaround available
**Affects**: All versions
**Description**: `str(system1.DisplayText)` can raise UnicodeEncodeError
when the display text contains non-ASCII characters (e.g., Chinese locale).
**Workaround**: Avoid calling `str()` on Workbench .NET objects that may
contain Unicode. Use fixed strings instead of querying display names.
