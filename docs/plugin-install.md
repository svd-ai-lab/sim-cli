# Optional solver packages

`sim scan` parses simulation files with `sim-cli-core` alone. Install a solver
package only when an agent also needs to detect a local solver, lint scripts,
or drive the solver. Each package adds:

- a driver, so `sim check`, `sim lint`, `sim run`, and `sim connect` work for
  that solver
- a bundled skill describing that solver's workflow, pitfalls, and inspection
  rules

The packages are developed in this repository under [`plugins/`](../plugins/)
and published as `sim-plugin-<solver>`.

| Solver | Package | Source |
|---|---|---|
| Abaqus | `sim-plugin-abaqus` | PyPI |
| Ansys Fluent | `sim-plugin-fluent` | PyPI |
| Ansys HFSS / Electronics Desktop | `sim-plugin-hfss` | PyPI |
| Ansys Mechanical | `sim-plugin-mechanical` | PyPI |
| Ansys Workbench | `sim-plugin-workbench` | PyPI |
| COMSOL Multiphysics | `sim-plugin-comsol` | PyPI |
| Altair HyperMesh | `sim-plugin-hypermesh` | Git |
| Ansys SpaceClaim | `sim-plugin-spaceclaim` | Git |
| Autodesk Fusion | `sim-plugin-autodeskfusion` | Git |
| Simcenter FloTHERM | `sim-plugin-flotherm` | Git |
| Simcenter STAR-CCM+ | `sim-plugin-starccm` | Git |

[`plugin-index.json`](../plugin-index.json) has the same list with exact
install specs and entry points.

## Install with uv

Run from the project root:

```bash
uv init  # only if this is not already a uv project
uv add sim-cli-core sim-plugin-comsol
uv run sim plugin sync-skills --target .agents/skills --copy
uv run sim check comsol
```

Packages marked Git in the table are not on PyPI yet; install them from this
repository:

```bash
uv add sim-cli-core "sim-plugin-flotherm @ git+https://github.com/svd-ai-lab/sim-cli.git#subdirectory=plugins/flotherm"
```

`uv run sim ...` runs `sim` from the current project environment, so it sees
the solver packages declared by that project. Bare `sim ...` runs whichever
`sim` is on `PATH`.

Other sources work the same way; keep the dependency in `pyproject.toml` so
another agent can reproduce the environment with `uv sync`:

```bash
uv add sim-cli-core sim-plugin-comsol==<version>
uv add sim-cli-core "sim-plugin-comsol @ git+https://github.com/svd-ai-lab/sim-cli.git@<tag-or-commit>#subdirectory=plugins/comsol"
uv add sim-cli-core ./sim_plugin_comsol-<version>-py3-none-any.whl
uv add sim-cli-core <path-to-sim-cli-checkout>/plugins/comsol
```

After changing dependencies, run `uv run sim plugin sync-skills` and
`uv run sim check <solver>` again from the same project.

## Without uv

Create and activate a normal Python virtual environment, then install into it.

macOS/Linux:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install sim-cli-core sim-plugin-comsol
sim plugin sync-skills --target .agents/skills --copy
sim check comsol
```

Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install sim-cli-core sim-plugin-comsol
sim plugin sync-skills --target .agents/skills --copy
sim check comsol
```

In an activated environment, bare `sim ...` is fine because the environment is
explicit.

## Skill sync targets

The Python package lives in site-packages; its skill is copied into a directory
the agent reads:

- `.agents/skills` for Codex and GitHub Copilot projects
- `.claude/skills` for Claude Code projects

If you omit `--target`, the CLI syncs to `./.claude/skills/` when `./.claude/`
exists and to `~/.claude/skills/` otherwise. Use `--copy` when symlinks are
inconvenient or unsupported. Re-running `sync-skills` is idempotent.

Tell the agent to run through the project with `uv run sim ...`, and never to
guess solver API names — inspect the live model or the solver's local docs
first.

## Live solver sessions

When an agent needs the solver held open across steps, `sim connect` starts a
local runtime and keeps the session alive. A bounded step is one modeling,
meshing, solving, or postprocessing action that can be inspected and verified
before continuing.

1. `uv run sim check <solver>`, then `uv run sim connect --solver <solver>`
2. `uv run sim inspect session.versions` before changing state — including after
   any human GUI edit, since a previous script may no longer match the session
3. `uv run sim exec --file step.py --label <step>` — one bounded step
4. `uv run sim inspect last.result`, verify with numeric evidence (mesh
   statistics, convergence, probes, conservation checks, tolerances), checkpoint
5. `uv run sim disconnect`, then `uv run sim stop` to free the local runtime

The bundled solver skill enforces the details, so give the agent the
engineering goal in plain language rather than a list of `sim` sub-steps.

## Solver commands

| Command | Use it for |
|---|---|
| `uv run sim check <solver>` | Detect local or remote solver installs. |
| `uv run sim lint <script>` | Validate a script before running it. |
| `uv run sim run script.py --solver <solver>` | Run a deterministic one-shot script. |
| `uv run sim logs last --field <name>` | Read back a one-shot run's parsed result. |
| `uv run sim connect --solver <solver>` | Open a persistent solver session. |
| `uv run sim exec --file step.py` | Run one bounded step in the live session. |
| `uv run sim inspect <target>` | Query session, result, or solver-specific state. |
| `uv run sim disconnect` / `uv run sim stop` | Tear down the session / stop the local runtime. |
| `uv run sim plugin list` / `info <solver>` | Show installed solver packages and their metadata. |
| `uv run sim plugin doctor <solver> --deep` | Check driver wiring, bundled skills, and solver detection. |
| `uv run sim setup` | Validate `sim.toml` and report the packages it declares. |

`plugin doctor` checks entry points, driver instantiation, bundled skills, and
compatibility metadata. `--deep` also calls solver detection, so it can fail
when the package is valid but the solver is missing, not available to the
current process, or installed in an unsupported location.

## Project manifests with sim.toml

For reproducible Python packages, commit `pyproject.toml` and `uv.lock`. Use
`sim.toml` for solver defaults, workspace settings, and optional package
declarations. Create a starter file with `uv run sim init`.

```toml
[sim]
default_solver = "comsol"
workspace = "./workspace"

[[sim.plugins]]
name = "comsol"
package = "sim-plugin-comsol"
```

Then a fresh checkout can run:

```bash
uv sync
uv run sim setup --dry-run
uv run sim plugin sync-skills --target .agents/skills --copy
uv run sim check comsol
```

`sim setup` validates `sim.toml` and reports the declared package specs. It
does not change the Python environment; use `uv add sim-cli-core <package-spec>`
and commit the resulting `pyproject.toml` / `uv.lock`.
