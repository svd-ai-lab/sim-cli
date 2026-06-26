# Changelog

## 0.1.1 - 2026-06-26

- Add bounded HFSS control-plane exec timeouts with timeout cleanup for owned AEDT sessions.
- Add `session.health` diagnostics with owned AEDT PID liveness, recent timeout cleanup, messages, and solve progress.
- Add HFSS model, boundary, setup, message, solution-progress, and Touchstone summary evidence helpers.
- Update the bundled HFSS skill guidance for bounded snippets, session health, and evidence-first workflows.

## 0.1.0 - 2026-05-06

- Bootstrap public HFSS 3D plugin package for sim-cli.
- Add lazy PyAEDT driver with no-AEDT unit coverage and opt-in real HFSS smoke coverage.
- Add broader AEDT discovery for regular and alternate AEDT launchers.
- Add a narrow PyAEDT 0.26.x AEDT startup compatibility shim.
- Add bundled HFSS skill and public documentation.
- Add CI, wheel-content checks, and a manual PyPI release workflow.
