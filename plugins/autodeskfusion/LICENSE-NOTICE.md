# License Notice

This repository (`sim-plugin-fusion360`) is licensed under [Apache-2.0](LICENSE)
and contains only the open-source driver glue between sim-cli and Autodesk
Fusion 360.

## What Is Not Included

This repository does not contain, redistribute, or otherwise bundle:

- Autodesk Fusion 360 binaries or installers
- Autodesk API stubs, headers, DLLs, SDK packages, or sample projects
- Fusion license files, license-server tooling, account tokens, or activation
  material
- Any proprietary Autodesk documentation or assets whose redistribution is
  restricted

## What You Must Supply

To use this plugin, you must independently install Autodesk Fusion 360 and use
it under your own valid Autodesk license. The live bridge runs inside the Fusion
GUI process and depends on the Fusion Python API provided by that installation.

## Interop

This plugin interacts with Fusion through its in-application Python API and a
small add-in that the user explicitly starts from Fusion's Scripts and Add-Ins
dialog. The host-side driver does not import Autodesk modules directly.

## Trademark Notice

"Autodesk" and "Fusion 360" are trademarks of Autodesk, Inc. This project is
not affiliated with or endorsed by Autodesk.
