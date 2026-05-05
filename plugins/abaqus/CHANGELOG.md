# Changelog

## 0.1.4 - 2026-05-05

- Add public `session.health` diagnostics with solver version, persistence,
  UI capabilities, last-run status, and bridge state.
- Expand `job.latest` / `job.diagnostics` inspection with last-result status
  and generated workspace artifacts.
- Refresh README, package metadata, bundled skill evidence, CI, and manual
  PyPI release workflow for public distribution.

## 0.1.3 - 2026-05-01

- Document the Abaqus embedded-Python boundary and host-side helper guidance.

## 0.1.2 - 2026-05-01

- Add the optional live noGUI Abaqus bridge backend for lower-latency trusted
  CAE authoring loops.

## 0.1.1 - 2026-05-01

- Add file-backed Abaqus/CAE authoring sessions with `connect`, `exec`, and
  `inspect` support.

## 0.1.0 - 2026-04-29

- Extract the Abaqus driver and bundled skill into an out-of-tree sim plugin.
- Add protocol conformance and initial packaging smoke tests.
