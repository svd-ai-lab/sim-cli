---
name: external-solver-discovery
description: "Discover and safely use external ad hoc solver capabilities, third-party skills, plugins, MCP servers, or native APIs when the host app or agent environment does not bundle a first-party solver path. Use for unsupported solver requests such as FDTD, Lumerical, Meep, openEMS, Tidy3D, gprMax, CST Studio Suite, or user-provided external integrations."
---

# External Solver Discovery

Use this skill when a user needs a solver, third-party plugin, MCP server,
native API, or cloud service that is not already covered by a bundled
solver-specific skill.

This skill is an ad hoc discovery layer. It does not make an external solver
supported, installed, licensed, authenticated, or available. It helps the agent
find credible local or user-configured routes and report evidence honestly.

## Required Protocol

1. Name the requested capability and distinguish it from bundled solver support.
   For example, HFSS support is 3D EM support, not FDTD support.
2. Check the current runtime before network-dependent discovery:
   - attached files and workspace extensions
   - project package files and scripts
   - installed commands, environment variables, registry/app paths, and common
     application locations
   - visible skills, plugins, MCP tools, connector tools, and native APIs
   - user-provided licenses, paths, profiles, or account hints
3. If a third-party skill, plugin, or MCP server is visible, inspect its own
   manifest, README, SKILL file, tool schema, or help output before using it.
   Prefer integrations that expose provenance, version, tool list, and logs.
4. Do not install packages, enable cloud services, consume a license seat, submit
   jobs, or authenticate accounts without user approval.
5. Probe the smallest real route first:
   - version or import check
   - open/list a project without solving
   - dry script parse
   - tiny example run
   - MCP health/tool-list call
6. Treat command success as transport evidence only. Engineering evidence must
   come from solver logs, exported data, result files, convergence, field data,
   S-parameters, or another domain-specific output requested by the user.
7. If no credible route is available, state exactly what is missing and give the
   narrowest next step, such as a vendor install path, Python environment,
   package install, MCP server command, API key, or license check.

## Candidate Selection

Prefer the user's already visible capability over installing a new one. Use
these tie-breakers:

- Project-native files first. A `.fsp` or `.lsf` project points to a different
  route than a Python Meep script.
- Local native APIs before GUI automation when they can expose the required
  state and logs.
- GUI automation only when the user needs visual operation or the API cannot
  expose the required state.
- Cloud APIs only when the user confirms account, credentials, data-sensitivity
  constraints, and job-cost expectations.
- sim-cli plugins when a matching plugin exists and standardized checks,
  session control, or plugin diagnostics materially reduce risk.

## FDTD Ad Hoc Checklist

The host app or agent environment may not bundle first-party FDTD support. When
a user asks for FDTD, Lumerical, Meep, openEMS, Tidy3D, gprMax, or files such as
`.fsp` or `.lsf`, treat the request as external ad hoc discovery.

Candidate routes to check:

- **Ansys Lumerical FDTD**: Prefer when the user has a licensed install or the
  workspace contains `.fsp` / `.lsf` files. Probe user-provided paths, common
  install locations, and the vendor Python API only after locating a real
  install. Do not attempt to install Lumerical or obtain licenses.
- **Meep**: Prefer when the project already has Python or Scheme Meep scripts,
  or an open-source scriptable FDTD path is acceptable. Probe the project
  Python/conda/container environment with an import or version check before any
  run. Ask before installing Meep or creating a new environment.
- **openEMS**: Prefer for RF, microwave, antenna, or PCB-oriented workflows,
  especially when MATLAB/Octave/Python openEMS scripts or CSXCAD references are
  present. Probe MATLAB, Octave, Python, and `PATH` before running examples.
- **Tidy3D**: Prefer only when the user confirms a Tidy3D account/API
  configuration and cloud submission is acceptable for the project data. Run
  local validation or no-submit construction before uploading or submitting a
  paid/cloud job.
- **gprMax**: Prefer for ground-penetrating radar or geophysical FDTD problems.
  Probe input files for gprMax directives and run a version/import check before
  any full model.

Common project signals include `.fsp`, `.lsf`, `.ctl`, `lumapi`, `import meep`,
`openEMS`, `CSXCAD`, `InitFDTD`, `RunOpenEMS`, `tidy3d`, `TIDY3D`, `gprMax`,
`#domain`, `#material`, and `#waveform`.

For any FDTD route, collect evidence from the actual tool or API: version or
install path, opened project or parsed script, run log, mesh/result metadata,
monitor exports, fields, flux data, S-parameters, HDF5/CSV output, or the
domain-specific result requested by the user.

## CST Third-Party Reference Checklist

The host app or agent environment may not bundle first-party CST Studio Suite
support. The public CAE-Agent-Hub repository can be used as a third-party
reference when the user explicitly wants a CST MCP route or CST workflow skill:

- CST MCP reference:
  `https://github.com/Cai-aa/CAE-Agent-Hub/tree/main/MCP/CST`
- CST workflow skill reference:
  `https://github.com/Cai-aa/CAE-Agent-Hub/tree/main/Skill/CST/cst-simulation-workflow`

Treat these URLs as discovery pointers, not bundled or audited support. Before
using them:

- Check local evidence first: `.cst` projects, CST Studio Suite install paths,
  `CST_INSTALL_ROOT`, visible MCP server registrations, visible skill folders,
  project package files, and user-provided paths or license hints.
- If CAE-Agent-Hub is present or the user asks to install it, inspect the
  repository README, CST MCP README, CST skill `SKILL.md`, and MCP tool surface
  from that checkout before running tools.
- Do not clone, install dependencies, register the MCP server, open CST, run a
  solver, or consume a CST license seat without user approval.
- Prefer a project-local checkout pinned to a tag or commit when installing.
  Avoid presenting a floating third-party `main` checkout as a reproducible
  integration.
- Verify the MCP transport with a health, detect, or tool-list probe before
  opening projects or invoking CST automation.
- Work on a copy of any user `.cst` project unless the user explicitly requests
  in-place modification.

For CST work, engineering evidence should come from the real CST route: detected
version or install path, opened project metadata, saved project path, solver log,
result tree entries, exported S-parameters, Touchstone files, field data,
far-field or near-field exports, sweep summaries, or the specific result the
user requested.

## Reporting

Keep the status crisp:

- `verified`: the runtime exposed the tool/API/MCP and a real probe succeeded.
- `available but unproven`: a likely install or config exists but no probe has
  run yet.
- `installable`: there is a known package/service route, but it is not present.
- `blocked`: a required install, license, credential, path, or network route is
  missing.

Never describe an ad hoc external route as bundled or first-party support.
