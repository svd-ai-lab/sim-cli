# sim-plugin-hfss

Use Codex, Claude Code, or another AI agent to work with
[Ansys HFSS](https://www.ansys.com/products/electronics/ansys-hfss) 3D
projects through [sim-cli](https://github.com/svd-ai-lab/sim-cli).

`sim-plugin-hfss` is an initial HFSS 3D driver plugin for sim-cli. It uses
PyAEDT as the Python control layer for Ansys Electronics Desktop (AEDT), keeps
the driver import-safe on machines without AEDT, and bundles an HFSS agent
skill so an agent has solver-specific workflow guidance after installation.

The HFSS/AEDT application is not bundled. See
[LICENSE-NOTICE.md](LICENSE-NOTICE.md).

## Current maturity

This is an initial alpha release. It has unit coverage, protocol conformance
coverage, simulated PyAEDT session coverage, packaging checks, and opt-in real
HFSS smoke coverage for hosts with AEDT available.

Use it as an integration starting point, not as proof that a production HFSS
workflow has been validated end to end.

## Scope

Version 0.1.1 targets HFSS 3D through PyAEDT's `ansys.aedt.core.hfss.Hfss`
interface.

Out of scope for this first version:

- HFSS 3D Layout
- Maxwell, Icepak, Q3D, Circuit, or generic AEDT workflows
- Direct `.aedt` or `.aedtz` batch solve without a PyAEDT script
- Plugin-index catalogue entry before the package is published and smoke-tested

## What an agent can do with HFSS

- Detect PyAEDT Python scripts that instantiate HFSS.
- Check whether AEDT appears to be installed on the host.
- Start a PyAEDT-backed HFSS session in graphical or non-graphical mode when
  AEDT is available.
- Execute bounded Python snippets against the active `hfss` object.
- Inspect session, project, and design summaries before continuing.
- Run complete PyAEDT Python scripts through `sim run --solver hfss`.

## Install

Install from PyPI:

```bash
uv pip install "sim-plugin-hfss==0.1.1"
```

For source testing against the current main branch:

```bash
uv pip install "git+https://github.com/svd-ai-lab/sim-plugin-hfss.git@main"
```

After installation, sim-cli should auto-discover the driver and bundled skill:

```bash
sim check hfss
sim run --solver hfss path/to/script.py
```

If `sim check hfss` reports that AEDT itself is unavailable, first confirm the
Python package installed correctly, then fix the local AEDT installation,
environment variables, or runtime prerequisites.

## AEDT discovery

The driver looks for AEDT using:

- `SIM_HFSS_AEDT_ROOT`
- `SIM_AEDT_ROOT`
- `ANSYSEM_ROOT*`
- AEDT launchers such as `ansysedt`, `ansysedt.exe`, or `ansysedtsv.exe` on
  `PATH`
- Windows Registry hints from AEDT/Ansys uninstall entries and `App Paths`
- conservative default Windows and Linux install roots

If AEDT is installed in a nonstandard location, set an explicit root:

```powershell
$env:SIM_HFSS_AEDT_ROOT = 'C:\path\to\AnsysEM'
sim check hfss
```

You do not need to add AEDT to the global system `PATH` when default discovery
or one of the explicit environment variables works.

## Common agent workflow

Use `sim-cli` when it adds discovery, session control, inspection, or artifact
tracking. Plain PyAEDT scripts, AEDT executables, and solver-native batch flows
are also valid when they are the narrower reliable path; keep the same evidence
standard either way.

1. Probe AEDT/HFSS availability, for example with `sim check hfss` or an
   equivalent PyAEDT/AEDT executable probe.
2. Choose GUI mode only when visual review is required; otherwise prefer
   non-graphical mode.
3. When using a live sim-cli session, inspect the active project/design before
   mutating anything:

   ```bash
   sim connect --solver hfss --ui-mode no_gui
   sim inspect session.summary
   sim inspect hfss.project.identity
   sim inspect hfss.design.summary
   ```

4. Run one bounded PyAEDT snippet, script, or native batch step at a time.
5. Inspect `last.result`, AEDT messages, exported artifacts, and design state
   before solving or exporting the next result.
6. Validate engineering results from HFSS artifacts and domain criteria, not
   from process success alone.

## Develop

```bash
git clone https://github.com/svd-ai-lab/sim-plugin-hfss
cd sim-plugin-hfss
uv sync --extra test
uv run pytest -q
uv build
```

The test suite is designed to pass on machines without AEDT/HFSS. Real solver
smoke testing is opt-in:

```bash
SIM_HFSS_RUN_INTEGRATION=1 uv run pytest tests/test_hfss_real_smoke.py -q
```

On PowerShell:

```powershell
$env:SIM_HFSS_RUN_INTEGRATION = '1'
uv run pytest tests/test_hfss_real_smoke.py -q
```

## License

Apache-2.0. See [LICENSE](LICENSE) and [LICENSE-NOTICE.md](LICENSE-NOTICE.md).
