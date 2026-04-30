---
name: install-sim-windows
description: Install sim-cli on Windows for an agent, including uv setup, sim-cli-core, and optional commercial plugin wheelhouse installation.
---

# Install sim-cli on Windows

Set up `sim-cli` for this Windows user. Keep everything user-local. Do not install vendor solvers or licenses; only install the sim runtime and wrapper plugins.

## Commands

Run in PowerShell.

```powershell
# 1. Prefer existing uv; otherwise install official uv.
where.exe uv
if ($LASTEXITCODE -eq 0) {
  $uv = "uv"
} else {
  powershell -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
  $uv = Join-Path $env:USERPROFILE ".local\bin\uv.exe"
}

# 2. Create a private runtime.
$root = Join-Path $env:LOCALAPPDATA "sim-cli"
$venv = Join-Path $root "venv"
New-Item -ItemType Directory -Force $root | Out-Null
& $uv venv $venv --python 3.12
$py = Join-Path $venv "Scripts\python.exe"
$sim = Join-Path $venv "Scripts\sim.exe"

# 3. Install sim-cli core.
& $uv pip install --python $py -U sim-cli-core

# 4. If the user has a private/commercial wheelhouse zip from sim / Cloudflare R2 / support, install it.
if (Test-Path ".\sim-commercial-plugins-win64.zip") {
  $wheelhouse = Join-Path $root "wheelhouse"
  Expand-Archive .\sim-commercial-plugins-win64.zip -DestinationPath $wheelhouse -Force
  & $uv pip install --python $py "$wheelhouse\*.whl"
}

# 5. Otherwise install the commercial preset by plugin name when network access allows it.
if (-not (Test-Path ".\sim-commercial-plugins-win64.zip")) {
  & $sim plugin install comsol
  & $sim plugin install ltspice
  & $sim plugin install fluent
  & $sim plugin install matlab
  & $sim plugin install mechanical
  & $sim plugin install abaqus
}

# 6. Validate.
& $sim --help
& $sim plugin list
& $sim check ltspice
```

## Notes

- Commercial preset: COMSOL, LTspice, Fluent, MATLAB, Ansys Mechanical, Abaqus.
- Do not install OpenFOAM, Cantera, CoolProp, PyBaMM, or demo/OSS plugins unless the user asks.
- If `uv` install is blocked, ask the user for a proxy, local `uv.exe`, local Python installer, or use the China/restricted-network install page.
- If a commercial `sim check <solver>` fails, it usually means the vendor solver, license, SDK, or environment path is missing; do not call that a failed sim install.
- Report back: `sim.exe` path, installed plugins, whether wheelhouse was used, and any blocked URL/domain.
