# License Notice

This repository (`sim-plugin-flotherm`) is licensed under [Apache-2.0](LICENSE) and contains **only** the open-source driver glue between sim-cli and Simcenter Flotherm.

## What is NOT included

This repository does **not** contain, redistribute, or otherwise bundle:

- Simcenter Flotherm binaries or installers
- Flotherm SDK / headers / DLLs
- Flotherm license files, license-server tooling, or activation tokens
- Any proprietary Siemens schema, documentation, or example projects whose redistribution is restricted

## What you must supply

To use this plugin, you must independently:

1. Install **Simcenter Flotherm** on a Windows host with your own valid Siemens license (see your Siemens account / your organization's license server).
2. Configure the Flotherm environment such that `flotherm.bat -env` resolves and `solexe.exe` / `translator.exe` are on `PATH`.

## Reverse engineering / interop

This plugin learns how to drive Flotherm through the publicly available `pywinauto` UIA tree, the publicly documented FloSCRIPT XML format, and the project-pack (`.pack`) file structure. No SDK, decompilation, or proprietary headers are used.

## Trademark notice

"Simcenter", "Flotherm", and related names are trademarks of Siemens AG. This project is not affiliated with or endorsed by Siemens.
