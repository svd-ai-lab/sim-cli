# Changelog

## Unreleased

- Rename the plugin to `sim-plugin-autodeskfusion`, with solver id
  `autodeskfusion` and import package `sim_plugin_autodeskfusion`.
- Replace the custom `SimFusionBridge` add-in transport with Autodesk Fusion's
  official local MCP server via the official MCP Python SDK.
- Update bundled skill guidance to prefer direct MCP exploration and treat
  `sim` as an optional control plane.
- Align README, CI, and bundled skill guidance with the sim uv-first workflow.
- Track `uv.lock` for reproducible local and CI environments.

## 0.1.0

- Initial Fusion 360 live-session driver scaffold.
- Added file-backed Fusion add-in bridge resources.
- Added import-safe detection, linting, run staging, and tests.
