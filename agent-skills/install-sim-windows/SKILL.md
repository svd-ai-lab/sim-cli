---
name: install-sim-windows
description: Install sim-cli on Windows for agent-driven commercial solver workflows. Use when asked to set up uv, sim-cli-core, and selected sim plugins such as COMSOL, LTspice, Fluent, MATLAB, Ansys Mechanical, or Abaqus on a normal network.
---

# Install sim on Windows

## Overview

Set up `sim-cli` on a Windows host for an agent. Prefer user-local installs, avoid changing global PATH or global pip configuration unless the user asks, and install only sim wrapper plugins, not vendor solver binaries or licenses.

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

Do not install OpenFOAM, Cantera, CoolProp, PyBaMM, or other OSS/demo plugins unless the user explicitly asks. Explain that commercial solver plugins require the user's existing licensed COMSOL, Ansys, MATLAB, Abaqus, or LTspice installation where applicable.

## Workflow

Run commands in PowerShell.

1. Check for existing tools:

```powershell
where.exe uv
uv --version
py -0p
python --version
```

2. Install `uv` if it is missing:

```powershell
powershell -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
```

If official `uv` install is blocked, ask the user for a proxy, local `uv.exe`, local Python installer, or use the China-specific skill.

3. Create a user-local runtime:

```powershell
$root = Join-Path $env:LOCALAPPDATA "sim-cli"
$venv = Join-Path $root "venv"
New-Item -ItemType Directory -Force $root | Out-Null
uv venv $venv --python 3.12
$py = Join-Path $venv "Scripts\python.exe"
$sim = Join-Path $venv "Scripts\sim.exe"
```

If Python 3.12 cannot be resolved, use an installed Python 3.10, 3.11, or 3.12.

4. Install `sim-cli-core`:

```powershell
uv pip install --python $py -U sim-cli-core
```

5. Install private/commercial plugins from a wheelhouse zip when the user has one:

```powershell
$wheelhouse = Join-Path $root "wheelhouse"
Expand-Archive .\sim-commercial-plugins-win64.zip -DestinationPath $wheelhouse -Force
uv pip install --python $py "$wheelhouse\*.whl"
```

Use this path for licensed/private plugins distributed through Cloudflare R2, CDN, customer portal, or support. It avoids GitHub auth and pip private-index complexity.

6. If the user does not have a wheelhouse, try the named plugin flow:

```powershell
& $sim plugin install comsol
& $sim plugin install ltspice
& $sim plugin install fluent
& $sim plugin install matlab
& $sim plugin install mechanical
& $sim plugin install abaqus
```

7. Validate:

```powershell
& $sim --help
& $sim plugin list
& $sim check ltspice
```

Run `sim check <solver>` only for solvers the user has installed. For commercial solvers, a failed check usually means the vendor software, license, environment variable, or SDK path is missing; do not treat that as a failed sim install.

## Report Back

Return the installed `sim.exe` path, selected plugins, wheelhouse path if used, and any blocked domains. If setup could not complete, give the exact command that failed and the shortest next action.
