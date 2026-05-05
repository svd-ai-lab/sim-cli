# sim-plugin-abaqus

Use Codex, Claude Code, or another AI agent to work with
[Dassault Systemes SIMULIA Abaqus](https://www.3ds.com/products/simulia/abaqus)
input decks and Abaqus/CAE Python scripts through
[sim-cli](https://github.com/svd-ai-lab/sim-cli).

`sim-plugin-abaqus` gives an agent practical Abaqus control paths: run `.inp`
decks, run Abaqus/CAE Python scripts in Abaqus's embedded interpreter, keep an
iterative noGUI CAE authoring session, inspect runtime health, collect model
summaries, read job diagnostics, and report generated artifacts such as `.dat`,
`.msg`, `.sta`, `.cae`, and `.odb` files.

The Abaqus application is not bundled. Bring your own Abaqus installation and
license. See [LICENSE-NOTICE.md](LICENSE-NOTICE.md).

This plugin is for Dassault SIMULIA Abaqus, not Ansys Mechanical. Use the
Mechanical plugin for PyMechanical and Ansys Mechanical sessions.

## What an agent can do with Abaqus

- Run complete Abaqus input decks with `sim run --solver abaqus model.inp`.
- Run Abaqus/CAE Python scripts through Abaqus's embedded Python.
- Build and debug CAE models incrementally with `connect`, `exec`, and
  `inspect`.
- Use a file-backed authoring session for conservative step-by-step work.
- Use the optional noGUI bridge backend for lower-latency trusted local loops.
- Inspect `session.health`, `cae.model_summary`, `workdir.files`, and
  `job.latest` before continuing a workflow.
- Treat solver completion as one signal, then validate against engineering
  acceptance criteria.

## Choose the right Abaqus workflow

### 1. Batch input-deck execution

Use this when the model is already fully specified as an Abaqus `.inp` deck:

```powershell
sim lint path/to/model.inp
sim run --solver abaqus path/to/model.inp
```

Abaqus writes output artifacts next to the deck. Inspect `.msg`, `.sta`, `.dat`,
and `.odb` outputs before treating the result as accepted.

### 2. Abaqus/CAE Python script execution

Use this when the model is authored by a complete Abaqus/CAE Python script:

```powershell
sim lint path/to/model.py
sim run --solver abaqus path/to/model.py
```

The plugin invokes `abaqus cae noGUI=<script>`, so Abaqus modules are imported
inside Abaqus's embedded interpreter, not inside the sim-cli Python process.

### 3. Iterative CAE authoring session

Use this when an agent should build, inspect, debug, and report a model across
multiple bounded snippets:

```powershell
sim connect --solver abaqus --mode cae --ui-mode no_gui
sim inspect session.health
sim exec --file step.py
sim inspect cae.model_summary
sim inspect job.latest
```

The default file-backed backend starts Abaqus/CAE for each snippet, loads the
session `.cae` database, mutates it, saves it, and returns diagnostics. This is
the safest default for public agent workflows.

For trusted local workspaces that need faster repeated snippets, request the
bridge backend:

```powershell
sim connect --solver abaqus --mode cae --ui-mode no_gui --driver-option backend=bridge
```

Bridge mode starts one long-lived noGUI CAE process on localhost with a
per-session token. Use it only in workspaces trusted by the user running the
session.

## Prerequisites

Install these before asking an agent to use this plugin:

- Python 3.10 or newer.
- [uv](https://docs.astral.sh/uv/) for Python environment and package installs.
- sim-cli or a project environment where sim-cli can be installed.
- A local Abaqus installation available through `abaqus.bat`, `abqNNNN.bat`, or
  an explicit launcher path.

If Abaqus is installed but not discoverable, point the driver at the launcher:

```powershell
$env:SIM_ABAQUS_COMMAND = 'C:\SIMULIA\Commands\abq2026.bat'
sim check abaqus
```

The plugin does not include Abaqus, vendor binaries, vendor SDKs, or licensed
example content. It installs the Python adapter and bundled agent guidance only.

## Install

For most users and agents, install the latest published PyPI version:

```powershell
uv pip install sim-plugin-abaqus
```

You can also install through sim-cli's plugin command:

```powershell
sim plugin install sim-plugin-abaqus
```

For quick testing of the current source branch, install from GitHub:

```powershell
uv pip install "git+https://github.com/svd-ai-lab/sim-plugin-abaqus.git@main"
```

For a reproducible agent run, pin a commit SHA:

```powershell
uv pip install "git+https://github.com/svd-ai-lab/sim-plugin-abaqus.git@<commit-sha>"
```

## Verify Install

After installation, sim-cli should auto-discover the driver and bundled skill:

```powershell
sim check abaqus
```

If `sim check abaqus` reports that Abaqus itself is unavailable, first confirm
the Python package installed correctly, then fix the local Abaqus launcher or
license prerequisites.

## Connect And Inspect Health

Use a noGUI authoring session for bounded agent-driven CAE work:

```powershell
sim connect --solver abaqus --mode cae --ui-mode no_gui
sim inspect session.health
sim inspect cae.model_summary
sim inspect workdir.files
```

Use one-shot execution for complete decks or scripts:

```powershell
sim run --solver abaqus path/to/job.inp
sim run --solver abaqus path/to/cae_script.py
```

## Common Agent Workflow

1. Confirm `sim check abaqus` is `ok`.
2. Choose batch `.inp`, complete CAE script, or iterative CAE authoring.
3. Gather geometry, materials, loads, boundary conditions, analysis type, and
   acceptance criteria before changing the model.
4. Run one bounded deck, script, or CAE snippet.
5. Inspect `session.health`, `cae.model_summary`, `workdir.files`, and
   `job.latest`.
6. Validate solver artifacts against physics-based acceptance criteria, not
   just exit code.

## Troubleshooting

- `sim` command not found: install sim-cli in the same Python environment.
- Driver not discovered: reinstall the plugin and run `sim check abaqus`.
- Abaqus not detected: set `SIM_ABAQUS_COMMAND` to the exact launcher path.
- A `.py` script imports fail in normal Python: run it through
  `sim run --solver abaqus script.py`; Abaqus modules live in Abaqus's embedded
  interpreter.
- A job exits with code `0` but results look wrong: inspect `.msg`, `.sta`,
  `.dat`, and `.odb` outputs and compare against engineering criteria.
- Bridge backend stops responding: inspect `session.health`, disconnect, and
  reconnect with the default file-backed backend before continuing.

## Agent quickstart

Give an agent this instruction when the task is about Abaqus:

```text
Use the bundled Abaqus skill from sim-plugin-abaqus. First identify whether the
task needs a batch .inp run, a complete Abaqus/CAE Python script run, or an
iterative noGUI CAE authoring session. Confirm `sim check abaqus` first. For
iterative work, connect with `sim connect --solver abaqus --mode cae --ui-mode
no_gui`, run one bounded snippet at a time, then inspect `session.health`,
`cae.model_summary`, `workdir.files`, and `job.latest`. Validate against
physics-based acceptance criteria, not only exit code.
```

The bundled skill entry point is:

```text
src/sim_plugin_abaqus/_skills/abaqus/SKILL.md
```

## How it relates to sim-cli

`sim-plugin-abaqus` extends sim-cli with the Abaqus-specific driver and bundled
Abaqus skill. sim-cli supplies the common runtime surface (`check`, `lint`,
`run`, `connect`, `exec`, and `inspect`), while this plugin supplies Abaqus
detection, subprocess execution, CAE authoring, health checks, model summaries,
job diagnostics, and bundled Abaqus agent guidance.

The plugin registers three entry-point groups:

```toml
[project.entry-points."sim.drivers"]
abaqus = "sim_plugin_abaqus:AbaqusDriver"

[project.entry-points."sim.skills"]
abaqus = "sim_plugin_abaqus:skills_dir"

[project.entry-points."sim.plugins"]
abaqus = "sim_plugin_abaqus:plugin_info"
```

## Develop

```bash
git clone https://github.com/svd-ai-lab/sim-plugin-abaqus
cd sim-plugin-abaqus
uv sync
uv run pytest tests -m "not integration"
```

End-to-end tests require a local Abaqus installation and are skipped unless
their prerequisites are available.

## License

Apache-2.0. See [LICENSE](LICENSE) and [LICENSE-NOTICE.md](LICENSE-NOTICE.md).
