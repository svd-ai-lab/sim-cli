# Mechanical — known issues

## 1. Chinese (CJK) locale corrupts any gRPC response containing CJK bytes

**Symptom**: `run_python_script` call fails with

```
_MultiThreadedRendezvous: status = StatusCode.UNKNOWN
details = "'ascii' codec can't decode byte 0 in position 0: ordinal not in range"
```

Empirically confirmed on Chinese Windows 11 + Ansys 24.1 +
PyMechanical 0.12.4: returning `ExtAPI.DataModel.Project.Name` (which
defaults to "项目") blows up the gRPC response layer. The channel
stays alive — subsequent calls succeed.

**Fields that are unsafe to return directly** on CJK locale:

- `ExtAPI.DataModel.Project.Name`
- `ExtAPI.DataModel.Project.ProjectDirectory`
- Any `.Name` on an object the user may have renamed to CJK
- Any `.DisplayString` on a message containing CJK

**Workaround** — normalize to ASCII inside the snippet *before*
`json.dumps`:

```python
def _safe(obj):
    s = str(obj)
    return "".join(c if ord(c) < 128 else "?" for c in s)
```

All stock skill snippets (01, 02, 06) use this pattern. Never return
raw `.Name` fields over gRPC without wrapping.

**Why it's hard to fix upstream**: PyMechanical 0.12 serializes the
gRPC return string assuming UTF-8, but Mechanical's IronPython
`unicode → str` coercion uses the system default (GBK on Chinese
Windows). The mismatch manifests as a null byte in the stream header.

## 1b. Multi-statement one-liners lose the return value

**Symptom**: `d.run("import json; json.dumps({'a':1})")` returns empty
stdout.

**Cause**: IronPython's `eval`-path only captures the last *bare*
expression. When statements are joined with `;`, the `json.dumps(...)`
call is treated as a statement and its value is discarded.

**Fix**: always use multi-line snippets with the last line being a bare
expression — no trailing semicolons, no assignment:

```python
import json
result = {"a": 1}
json.dumps(result)   # <-- this line, by itself, as the last line
```

## 2. `batch=False` needed for sim screenshot to work

**Symptom**: `sim screenshot` shows an empty desktop or just the
taskbar after a Mechanical session launches.

**Cause**: `launch_mechanical(batch=True)` starts `AnsysWBU.exe` with
no window — nothing for `PIL.ImageGrab` to capture.

**Fix**: MechanicalDriver defaults to `batch=False`. Only override with
`ui_mode="batch"` if you explicitly do not need screenshots.

## 3. `Location = body` silently fails

**Symptom**: You set `fixed_support.Location = body`, no exception,
but solve fails with "missing scoping" or "no support".

**Cause**: BCs require `NamedSelection` or `SelectionInfo`, not raw
`Body` objects. See `reference/bc_scoping.md`.

**Fix**: Use a NamedSelection (preferred) or build a `SelectionInfo`
from face IDs.

## 4. `Solve(True)` blocks gRPC — can't cancel mid-solve via SDK

**Symptom**: Hit a runaway solve, no way to cancel via `exec`.

**Cause**: The gRPC request is blocked on the solve. Sending another
request queues behind it.

**Workaround**: From a *different* terminal:

```bash
sim screenshot -o state.png      # this still works, independent path
# click Stop in the GUI (observable in the screenshot), or
# kill AnsysWBU.exe from Task Manager
```

## 5. `Model.Mesh.Nodes` is an int, not a collection

**Symptom**: `AttributeError: 'int' object has no attribute 'Count'`

**Cause**: In 24.1 scripting, `Nodes` and `Elements` expose the *count*
directly as an int. To iterate nodes, use `Model.Mesh.MeshDataByName[...]`
or the DPF pipeline.

## 6. IronPython 2.7 quirks

- No f-strings: use `"%s" % x` or `"{}".format(x)`.
- `print` works, but do not rely on `end=` keyword.
- No `typing`. No `pathlib`. Use `os.path`.
- `json` module exists and works for simple dicts.

## 7. `launch_mechanical(version=...)` requires an integer

**Symptom**: `TypeError: int expected`

**Cause**: `version` param is `int`, not str. MechanicalDriver converts
`"24.1"` → `241` via `_version_code`. Do not pass "24.1" through directly.

## 8. License contention on repeated launch/exit cycles

**Symptom**: Second `launch_mechanical` hangs at "Waiting for license".

**Cause**: Previous instance did not fully release the seat within the
license server's grace window.

**Workaround**: `cleanup_on_exit=False` on launch keeps the driver in
control of shutdown; `mech.exit()` blocks until the seat is released.
If you hit this anyway, wait ~30 s and retry.

## 9. "Script Error" dialog blocks geometry import in GUI mode

**Symptom**: `run_python_script` with `GeometryImport.Import(...)` hangs
indefinitely. Mechanical's GUI shows a modal "Script Error" dialog
(line 61671, "操作非法").

**Cause**: Mechanical 24.1's internal JavaScript UI layer throws
during tree update after SpaceClaim imports geometry. Affects only
`batch=False` (GUI) mode.

**Workaround**: Dismiss the dialog programmatically from a separate
thread or process:

```python
import subprocess
subprocess.run(["powershell", "-Command", """
Add-Type @"
using System; using System.Runtime.InteropServices;
public class W { [DllImport("user32.dll")] public static extern IntPtr FindWindow(string c, string t);
                 [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l); }
"@
$h = [W]::FindWindow('#32770', 'Script Error')
if ($h -ne [IntPtr]::Zero) { [W]::PostMessage($h, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) }
"""])
```

The E2E test script (`mechanical_e2e_static_structural.py`) includes a
`dismiss_dialogs()` helper that runs this automatically.

## 10. ALL `.Name` fields are unsafe on CJK locale, not just `Project.Name`

**Symptom**: Same as #1, but happens when returning ANY object's `.Name`
— boundary condition names (固定约束, 无摩擦支撑, 远端力, 热条件),
result names, coordinate system names, etc.

**Cause**: Mechanical 24.1 on Chinese locale defaults ALL object names
to Chinese. The issue is identical to #1 but broader in scope.

**Fix**: Never include `.Name` in the json.dumps return value. Return
counts and numeric results only. If you need names, use the `_safe()`
pattern from #1, but be aware that even `_safe()` may not protect
against ALL encoding paths in PyMechanical 0.12.4.

## 11. Windows Firewall prompt for `mpiexec.exe` on first solve

**Symptom**: First-ever `Solve(True)` on a machine triggers a Windows
Security Alert asking to allow `mpiexec.exe` (Intel Corporation) through
the firewall.

**Cause**: ANSYS solver uses Intel MPI for parallel processing. Does NOT
actually block the solve — it completes anyway — but the dialog is
visible in screenshots.

**Fix**: Pre-approve `mpiexec.exe` in Windows Firewall settings, or
accept it once during first run.
