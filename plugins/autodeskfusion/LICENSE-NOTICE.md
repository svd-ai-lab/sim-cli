# License Notice

This repository (`sim-plugin-autodeskfusion`) is licensed under
[Apache-2.0](LICENSE) and contains only the open-source driver glue between
sim-cli, agents, and Autodesk Fusion.

## What Is Not Included

This repository does not contain, redistribute, or otherwise bundle:

- Autodesk Fusion binaries or installers
- Autodesk API stubs, headers, DLLs, SDK packages, or sample projects
- Fusion license files, license-server tooling, account tokens, or activation
  material
- Any proprietary Autodesk documentation or assets whose redistribution is
  restricted

## What You Must Supply

To use this plugin, you must independently install Autodesk Fusion and use it
under your own valid Autodesk license. The plugin calls the official local
Fusion MCP server and depends on the Fusion Python API provided by that
installation.

## Interop

This plugin interacts with Fusion through Autodesk's local MCP server. The
host-side driver does not import Autodesk modules directly.

## Trademark Notice

"Autodesk" and "Fusion" are trademarks of Autodesk, Inc. This project is
not affiliated with or endorsed by Autodesk.
