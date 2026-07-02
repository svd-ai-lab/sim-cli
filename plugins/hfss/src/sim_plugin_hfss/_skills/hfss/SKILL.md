---
name: hfss
description: "Work with Ansys HFSS 3D through PyAEDT, AEDT, sim-plugin-hfss, or solver-native workflows. Use when the user asks an agent to inspect, build, edit, run, monitor, export, or debug HFSS 3D models."
---

# HFSS Skill

Use this skill for Ansys HFSS 3D work.

This plugin targets HFSS 3D through PyAEDT and AEDT. It does not yet cover HFSS
3D Layout, Maxwell, Icepak, Q3D, Circuit, or generic AEDT workflows.

`sim-cli` is a control and observability layer, not the only valid execution
path. Use `sim check`, `sim connect`, `sim inspect`, and bounded `sim exec`
snippets when they add discovery, session control, or structured evidence. Use
plain PyAEDT scripts, AEDT executables, vendor batch flows, or GUI operation
when those are the narrower reliable primitive. The evidence standard is the
same for every path.

## Required Protocol

1. Run an HFSS/AEDT availability probe before launch or solve.
   - Use `sim check hfss` when `sim-cli` is available.
   - Acceptable alternatives: a PyAEDT import/version probe, AEDT executable
     path probe, Windows Registry/default-install probe, or environment variable
     probe.
   - When probing nested Python packages such as `ansys.aedt.core`, catch
     `ModuleNotFoundError`; a missing top-level `ansys` package is evidence that
     the control package is absent, not a reason to launch AEDT for discovery.
   - Do not use `-help` on `ansysedt.exe`, `ansysedtsv.exe`, or `hfss.exe` as
     an availability probe. AEDT Student can open a modal `Electronics Desktop
     Student Help` window and block automation when launched this way.
   - Missing `sim-cli` is not evidence that AEDT/HFSS is missing.
2. If no AEDT installation is found, stop and ask for an AEDT installation or
   `SIM_HFSS_AEDT_ROOT` path. Do not invent install paths.
3. Prefer no-GUI operation unless the user needs visual review or the workflow
   cannot expose the required state programmatically.
4. Before setup, solve, export, or result interpretation, inspect the active
   project/design using the best available path:

```bash
sim inspect session.summary
sim inspect hfss.project.identity
sim inspect hfss.design.summary
sim inspect hfss.model.summary
sim inspect hfss.boundaries.summary
sim inspect hfss.setups.summary
```

   If you are not using `sim-cli`, collect equivalent project, design, object,
   boundary, port, setup, and sweep information through PyAEDT or AEDT APIs.
5. Run one bounded step at a time. After each mutation, inspect the changed
   state and capture `last.result`, script output, or equivalent logs.
6. Treat process success as transport success only. Engineering acceptance must
   come from HFSS results, exported data, convergence, S-parameters, fields,
   far-field quantities, or another domain-specific criterion requested by the
   user.
7. Keep failed evidence. If a solve/export fails, capture AEDT messages,
   stdout/stderr, generated files, and the exact step that failed.

## Common Workflows

### Connect Through sim-cli

```bash
sim check hfss
sim connect --solver hfss --ui-mode no_gui
sim inspect session.summary
sim inspect hfss.project.identity
sim inspect hfss.design.summary
```

Use GUI mode only when the user needs to watch or interact with AEDT:

```bash
sim connect --solver hfss --ui-mode gui
```

### Run a PyAEDT Script

Use this for a complete script that constructs or opens an HFSS project:

```bash
sim lint --solver hfss path/to/script.py
sim run --solver hfss path/to/script.py
```

Direct execution is also acceptable when it is clearer:

```bash
python path/to/script.py
```

In either case, preserve the AEDT project, logs, exported reports, and numeric
acceptance results.

### Execute a Bounded Snippet

After `sim connect`, snippets can use the live `hfss` object:

```python
{
    "project": hfss.project_name,
    "design": hfss.design_name,
    "setups": list(hfss.setup_names),
}
```

Prefer JSON-serializable results. Use `sim inspect last.result` after each
snippet.

Control-plane snippets are bounded by the HFSS driver by default. To tighten or
disable that bound for a session, pass an explicit driver option:

```bash
sim connect --solver hfss --ui-mode no_gui --driver-option exec_timeout_s=60
```

Use short bounds for inspection, setup edits, and exporter snippets. Do not use
a fixed wall-clock timeout as the failure signal for real solves; solve-like
snippets such as `analyze_setup(...)` are not given the driver's default control
timeout unless you explicitly set `exec_timeout_s`. If a snippet returns
`hung: true`, treat the session as quarantined: inspect `session.health`, then
reconnect before more HFSS work.

### Export and Parse S-Parameters

When Touchstone export is available, export `.sNp` and parse it directly for
acceptance metrics. The connector exposes a best-effort helper in snippets:

```python
touchstone_summary("path/to/result.s1p", target_frequencies_ghz=[5.8], threshold_db=-10)
```

Do not require `scikit-rf` just to compute minimum S-parameter, target-frequency
values, or threshold bandwidth.

## Monitoring and Evidence

Use these inspections when available:

- `hfss.model.summary` for object names, sheet/solid grouping, materials, and
  bounding boxes when PyAEDT exposes them.
- `hfss.boundaries.summary` for boundaries, excitations, ports, and associated
  objects when available.
- `hfss.setups.summary` for setup and sweep names/properties.
- `hfss.messages` for AEDT errors/warnings/info.
- `hfss.solution.progress` for best-effort solved frequency progress from
  `.aedtresults` files.
- `session.health` for PyAEDT/AEDT liveness, tracked owned AEDT PIDs, recent
  timeout cleanup, recent messages, and best-effort solve progress.

If an inspection is unavailable, report that honestly and use a solver-native
fallback. Do not fabricate status.

## Modeling Gotchas

- AEDT Student installs use the student launcher and may expose version strings
  such as `2025.2SV`. The connector patches PyAEDT 0.26.x startup handling for
  this case, but direct scripts may need the same care.
- If an `Electronics Desktop Student Help` dialog appears during automation,
  close it, record the exact command, and remove `-help` from the probe path.
  Use Registry/path/import checks for discovery, or run a real script
  invocation when the task needs AEDT execution.
- For small antenna feeds between curved conductors, do not rely on
  `lumped_port(..., create_port_sheet=True)` until the generated sheet has been
  visually or solver-message validated. HFSS can create a non-planar port sheet
  between round objects, which fails during port refinement. Prefer an explicit
  planar sheet plus an explicit two-point integration line.
- Save the project before a real solve smoke, and capture
  `hfss.odesktop.GetMessages(...)` immediately after `analyze_setup(...)`
  returns false. Reopening the project later can lose the most useful failure
  context.
- For GUI evidence on Windows, inspect the screenshot after taking it. If a
  full-desktop capture is black, capture the AEDT window by handle instead of
  treating the file's existence as visual proof.

## First-Version Limits

- Direct `.aedt` and `.aedtz` solving through `sim run` is not validated yet.
- Real HFSS release validation is opt-in and must be recorded separately from
  ordinary no-AEDT unit tests.
- Do not claim solver correctness from plugin unit tests alone.

## Troubleshooting

- Driver not discovered: only when using `sim-cli`, reinstall the plugin in
  the same environment as sim-cli and rerun `sim check hfss`.
- AEDT not detected: set `SIM_HFSS_AEDT_ROOT` to the directory containing an
  AEDT launcher, or rely on Registry/default discovery for common install
  layouts. A permanent global `PATH` change is optional, not required.
- PyAEDT import error: install `pyaedt>=0.26.3,<1` in the active environment.
- Script not detected: make sure it constructs HFSS through PyAEDT, for example
  `from ansys.aedt.core.hfss import Hfss` followed by `Hfss(...)`.
