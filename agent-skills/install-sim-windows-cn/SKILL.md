---
name: install-sim-windows-cn
description: Install sim-cli on Windows in China or restricted networks for agent-driven commercial solver workflows. Use when GitHub, PyPI, uv downloads, or plugin indexes may be blocked and the user needs mirror, proxy, local wheelhouse, or Cloudflare R2 fallback guidance.
---

# Install sim on Windows in China

## Overview

Set up `sim-cli` on a Windows host when network access may be unreliable. Prefer user-local installs, PyPI mirrors, and local wheelhouse zips. Do not install vendor solver binaries or licenses.

## Plugin Preset

Use these plugin names unless the user asks for a different set:

| Solver label | sim plugin | Python package |
| --- | --- | --- |
| COMSOL Multiphysics | `comsol` | `sim-plugin-comsol` |
| LTspice | `ltspice` | `sim-plugin-ltspice` |
| Ansys Fluent | `fluent` | `sim-plugin-fluent` |
| MATLAB | `matlab` | `sim-plugin-matlab` |
| Ansys Mechanical | `mechanical` | `sim-plugin-mechanical` |
| Abaqus/CAE | `abaqus` | `sim-plugin-abaqus` |

Do not install OpenFOAM, Cantera, CoolProp, PyBaMM, or other OSS/demo plugins unless the user explicitly asks. Explain that this installs sim wrapper plugins only; users still need their own licensed COMSOL, Ansys, MATLAB, Abaqus, or LTspice installation where applicable.

## Workflow

Run commands in PowerShell. Use `$env:UV_DEFAULT_INDEX` for the current session rather than changing global pip/uv config unless the user asks.

1. Check for existing tools:

```powershell
where.exe uv
uv --version
py -0p
python --version
```

2. Prefer installing `uv` through an existing Python and a China-accessible PyPI mirror:

```powershell
$env:UV_DEFAULT_INDEX = "https://pypi.tuna.tsinghua.edu.cn/simple"
py -3 -m pip install --user -U uv -i $env:UV_DEFAULT_INDEX
$userBase = py -3 -m site --user-base
$uv = Join-Path $userBase "Scripts\uv.exe"
& $uv --version
```

If `py` is unavailable, try `python -m pip install --user -U uv -i $env:UV_DEFAULT_INDEX` and compute `$userBase` with `python -m site --user-base`.

3. If Python is not installed or pip install fails, try official `uv` install methods:

```powershell
powershell -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
```

If the official installer is blocked, stop and report the failing domain or URL. Ask the user for a proxy, local `uv.exe`, local Python installer, or internal mirror. Do not invent unofficial mirrors.

4. Create a user-local runtime:

```powershell
$root = Join-Path $env:LOCALAPPDATA "sim-cli"
$venv = Join-Path $root "venv"
New-Item -ItemType Directory -Force $root | Out-Null
& $uv venv $venv --python 3.12
$py = Join-Path $venv "Scripts\python.exe"
$sim = Join-Path $venv "Scripts\sim.exe"
```

If Python 3.12 cannot be resolved, use an installed Python 3.10, 3.11, or 3.12. Avoid downloading Python through `uv` on restricted networks unless the user confirms network access.

5. Install `sim-cli-core` through the mirror first:

```powershell
$env:UV_DEFAULT_INDEX = "https://pypi.tuna.tsinghua.edu.cn/simple"
& $uv pip install --python $py -U sim-cli-core -i $env:UV_DEFAULT_INDEX
```

6. Install private/commercial plugins from a wheelhouse zip when available:

```powershell
$wheelhouse = Join-Path $root "wheelhouse"
Expand-Archive .\sim-commercial-plugins-win64.zip -DestinationPath $wheelhouse -Force
& $uv pip install --python $py "$wheelhouse\*.whl"
```

Prefer this path for private plugins distributed through Cloudflare R2, CDN, support, or an internal mirror. It avoids GitHub, private pip auth, and plugin-index access during installation.

7. If no wheelhouse is available, try public package names through the mirror:

```powershell
& $uv pip install --python $py -U `
  sim-plugin-comsol `
  sim-plugin-ltspice `
  sim-plugin-fluent `
  sim-plugin-matlab `
  sim-plugin-mechanical `
  sim-plugin-abaqus `
  -i $env:UV_DEFAULT_INDEX
```

If plugin packages are not available from the mirror, try the sim plugin flow:

```powershell
& $sim plugin install comsol
& $sim plugin install ltspice
& $sim plugin install fluent
& $sim plugin install matlab
& $sim plugin install mechanical
& $sim plugin install abaqus
```

If GitHub or the plugin index is blocked, ask the user for a wheelhouse folder or reachable package mirror, then install local wheels with:

```powershell
& $uv pip install --python $py C:\path\to\wheelhouse\*.whl
```

8. Validate:

```powershell
& $sim --help
& $sim plugin list
& $sim check ltspice
```

Run `sim check <solver>` only for solvers the user has installed. For commercial solvers, a failed check usually means the vendor software, license, environment variable, or SDK path is missing; do not treat that as a failed sim install.

## Report Back

Return the installed `sim.exe` path, selected plugins, mirror used, wheelhouse path if used, and any blocked domains. If setup could not complete, give the exact command that failed and the shortest next action: install Python, provide `uv.exe`, configure proxy, or provide a local wheelhouse.
