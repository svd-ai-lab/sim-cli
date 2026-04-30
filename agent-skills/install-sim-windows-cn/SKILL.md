---
name: install-sim-windows-cn
description: Install sim-cli on Windows for an agent in China or restricted networks, including PyPI mirror uv setup, sim-cli-core, local wheelhouse, and commercial plugin fallbacks.
---

# Install sim-cli on Windows in China

Set up `sim-cli` for this Windows user when GitHub, PyPI, or plugin indexes may be slow or blocked. Keep everything user-local. Do not install vendor solvers or licenses; only install the sim runtime and wrapper plugins.

## Commands

Run in PowerShell.

```powershell
# 1. Prefer existing uv; otherwise install uv through Python + Tsinghua PyPI mirror.
where.exe uv
if ($LASTEXITCODE -eq 0) {
  $uv = "uv"
} else {
  $env:UV_DEFAULT_INDEX = "https://pypi.tuna.tsinghua.edu.cn/simple"
  py -3 -m pip install --user -U uv -i $env:UV_DEFAULT_INDEX
  $userBase = py -3 -m site --user-base
  $uv = Join-Path $userBase "Scripts\uv.exe"
}

# 2. Create a private runtime.
$root = Join-Path $env:LOCALAPPDATA "sim-cli"
$venv = Join-Path $root "venv"
New-Item -ItemType Directory -Force $root | Out-Null
& $uv venv $venv --python 3.12
$py = Join-Path $venv "Scripts\python.exe"
$sim = Join-Path $venv "Scripts\sim.exe"

# 3. Install sim-cli core from mirror.
$env:UV_DEFAULT_INDEX = "https://pypi.tuna.tsinghua.edu.cn/simple"
& $uv pip install --python $py -U sim-cli-core -i $env:UV_DEFAULT_INDEX

# 4. Prefer private/commercial wheelhouse zip from sim / Cloudflare R2 / support.
if (Test-Path ".\sim-commercial-plugins-win64.zip") {
  $wheelhouse = Join-Path $root "wheelhouse"
  Expand-Archive .\sim-commercial-plugins-win64.zip -DestinationPath $wheelhouse -Force
  & $uv pip install --python $py "$wheelhouse\*.whl"
}

# 5. If no wheelhouse exists, try named plugins only when network access allows it.
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
- If `uv`, PyPI, GitHub, or the plugin index is blocked, ask for a proxy, local `uv.exe`, local Python installer, or `sim-commercial-plugins-win64.zip`.
- If a commercial `sim check <solver>` fails, it usually means the vendor solver, license, SDK, or environment path is missing; do not call that a failed sim install.
- Report back: `sim.exe` path, installed plugins, whether wheelhouse was used, mirror used, and any blocked URL/domain.
