---
name: hfss
description: "Work with Ansys HFSS 3D through sim-plugin-hfss and PyAEDT. Use when the user asks an agent to inspect, build, edit, run, or debug HFSS 3D models."
---

# HFSS Skill

Use this skill for Ansys HFSS 3D work through `sim-plugin-hfss`.

This initial plugin targets HFSS 3D through PyAEDT. It does not yet cover HFSS
3D Layout, Maxwell, Icepak, Q3D, Circuit, or generic AEDT workflows.

## Required Protocol

1. Run `sim check hfss` before launching or editing anything.
2. If `sim check hfss` reports `not_installed`, stop and ask the user for an
   AEDT installation or `SIM_HFSS_AEDT_ROOT` path. Do not invent install paths.
3. Prefer `--ui-mode no_gui` unless the user explicitly needs visual review.
4. Before setup, solve, export, or result interpretation, inspect:

```bash
sim inspect session.summary
sim inspect hfss.project.identity
sim inspect hfss.design.summary
```

5. Run one bounded PyAEDT snippet at a time.
6. Inspect `last.result` and the relevant project/design state after each
   mutation.
7. Treat process success as transport success only. Engineering acceptance must
   come from HFSS results, exported data, convergence, S-parameters, fields, or
   another domain-specific criterion requested by the user.

## Common Workflows

### Connect to HFSS

```bash
sim connect --solver hfss --ui-mode no_gui
sim inspect session.summary
sim inspect hfss.project.identity
sim inspect hfss.design.summary
```

Use GUI mode only when the user needs to watch AEDT:

```bash
sim connect --solver hfss --ui-mode gui
```

### Run a PyAEDT script

Use this for a complete script that constructs or opens an HFSS project:

```bash
sim lint --solver hfss path/to/script.py
sim run --solver hfss path/to/script.py
```

The script runs in the current Python environment. PyAEDT and AEDT must be
available there.

### Execute a bounded snippet

After `sim connect`, snippets can use the live `hfss` object:

```python
hfss.project_name
```

Return JSON-serializable data from the last expression when possible:

```python
{
    "project": hfss.project_name,
    "design": hfss.design_name,
    "setups": list(hfss.setup_names),
}
```

## Modeling Gotchas

- For small antenna feeds between curved conductors, do not rely on
  `lumped_port(..., create_port_sheet=True)` until the generated sheet has
  been visually or solver-message validated. HFSS can create a non-planar port
  sheet between round objects, which fails during port refinement. Prefer an
  explicit planar sheet plus an explicit two-point integration line.
- Save the project before a real solve smoke, and capture AEDT messages
  immediately after `analyze_setup(...)` if it returns false. Reopening the
  project later can lose the most useful failure context.
- For GUI evidence on Windows, inspect the screenshot after taking it. If a
  full-desktop capture is black, capture the AEDT window by handle instead of
  treating the file's existence as visual proof.

## First-Version Limits

- Direct `.aedt` and `.aedtz` solving is not validated yet.
- Real HFSS release validation is opt-in and must be recorded separately from
  ordinary no-AEDT unit tests.
- Do not claim solver correctness from plugin unit tests alone.

## Troubleshooting

- Driver not discovered: reinstall the plugin in the same environment as
  sim-cli and rerun `sim check hfss`.
- AEDT not detected: set `SIM_HFSS_AEDT_ROOT` to the directory containing
  an AEDT launcher, or rely on default discovery for common install layouts. A
  permanent global `PATH` change is optional, not required.
- PyAEDT import error: install `pyaedt>=0.26.3,<1` in the active environment.
- Script not detected: make sure it constructs HFSS through PyAEDT, for
  example `from ansys.aedt.core.hfss import Hfss` followed by `Hfss(...)`.
