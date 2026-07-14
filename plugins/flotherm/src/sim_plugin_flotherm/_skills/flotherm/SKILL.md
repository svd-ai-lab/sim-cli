---
name: flotherm-sim
description: Run, inspect, or troubleshoot Simcenter Flotherm thermal cases using the smallest verified local control path. Use for Flotherm installation checks, existing-project re-solves, .pack import, FloSCRIPT playback, model creation or modification, solver monitoring, and result extraction. Discover native and sim-cli capabilities before choosing a path; do not assume either is installed or connected.
---

# Flotherm

Control Simcenter Flotherm through the narrowest path that can produce the
requested evidence. A bundled skill does not prove that Flotherm, a license,
`sim-cli-core`, or `sim-plugin-flotherm` is installed.

## Start with capability discovery

Use one or two bounded probes before choosing an execution path:

1. Identify the requested operation and input:
   - installation or version lookup
   - unchanged existing-project re-solve
   - `.pack` import
   - first-time model creation or modification
   - solve monitoring or result extraction
2. Inspect the current runtime directly:
   - Flotherm install roots, `flotherm.bat`, `translator.exe`, and `solexe.exe`
   - the requested project, `.pack`, FloSCRIPT, logs, and result directories
   - interactive Windows desktop availability for GUI automation
   - an already available `sim` command or matching project environment
3. Choose a path from the table below. Do not install or download sim-cli merely
   to answer an availability, location, version, or saved-result question.

Do not infer that Flotherm is unavailable from a missing `sim` command. Do not
search transient package-manager caches for old `sim.exe` files as a normal
discovery path.

## Choose the execution path

| Task | Preferred path | Why |
|---|---|---|
| Locate Flotherm or report its version | Direct filesystem, environment, or Registry probe | No control runtime is needed |
| Inspect saved logs or result fields | Direct file reading | Avoid launching the solver |
| Re-solve an existing, unchanged project in `FLOUSERDIR` | Native `translator.exe` + `solexe.exe` | Verified headless path |
| Import a `.pack`, create a project, or modify model inputs | sim-cli GUI automation | Flotherm 2504 command-line FloSCRIPT playback is not verified end to end |
| Diagnose driver/session health or capture structured GUI evidence | Existing sim-cli session | Uses the plugin's session and diagnostic surfaces |

If the selected path requires sim-cli but the command or Flotherm plugin is
missing, explain the requirement and get the user's approval before downloading
or installing packages. Prefer the user's existing project environment and a
pinned public package source. Do not silently use a repository `main` branch for
an ephemeral install.

## Native batch re-solve

Use this only for an existing project that has already been imported or created
in `FLOUSERDIR` and does not need parameter or geometry changes:

```batch
call flotherm.bat -env
translator.exe -p "<FLOUSERDIR>\<project>.<GUID>" -n1
solexe.exe -p "<FLOUSERDIR>\<project>.<GUID>"
```

The native path can re-solve an existing project, including a crash-recovery
rerun. It cannot import a `.pack`, create a project, or apply model changes.

Check the project log at `DataSets/BaseSolution/PDTemp/logit` and the expected
result fields under `DataSets/BaseSolution/msp_*/end/`. Process exit alone is
not engineering acceptance.

## sim-cli GUI automation

Use this path when the task needs `.pack` import, FloSCRIPT playback, first-time
creation, or model modification. It requires an interactive Windows desktop;
Flotherm's Qt UI automation does not work in a non-interactive SSH session.

Use the package manager and environment already selected by the user. Typical
commands, once `sim` and the matching plugin are verified, are:

```powershell
uv run sim check flotherm
uv run sim connect --solver flotherm --ui-mode gui
uv run sim exec '<path>.pack'
uv run sim exec 'solve'
uv run sim exec 'status'
uv run sim disconnect
```

Keep the returned session id and pass it explicitly when commands do not share
environment state. Let the driver own the Flotherm process while UI automation
is active; concurrent user input can race with UI element discovery.

For model generation, write and lint small FloSCRIPT XML steps, execute one step
at a time, and save a project checkpoint after each successful mutation. Read
`base/reference/floscript_modeling.md` before authoring FloSCRIPT.

## Failure and retry rules

- Preserve the first failing command, status, logs, and screenshot before
  attempting a workaround.
- After a GUI playback failure, inspect the session once and capture one visual
  or log artifact when useful. Do not repeat an equivalent `exec` call unless a
  specific state change addresses the failure.
- Treat a missing file dialog, wrong foreground window, session mismatch, and
  non-interactive desktop as distinct failure classes.
- Use `plugin doctor --deep` only for a suspected plugin or protocol defect, not
  as a routine response to a solver/UI failure.
- Stop and report when the chosen path is unsupported, installation would be
  required without approval, or one bounded diagnostic cycle does not identify
  a corrective action.
- Disconnect only the session owned by the task. Do not terminate every process
  matching a generic Flotherm executable name.

## Validation and evidence

Before mutation or solve:

- confirm the exact input/project and Flotherm version
- confirm that the chosen path supports the requested operation
- define a result-based acceptance criterion
- lint FloSCRIPT or inspect the existing project when applicable

Before claiming completion:

- verify Flotherm's completion or convergence marker
- inspect expected project, log, and result artifacts
- extract a numeric engineering result when the task calls for one
- report the execution path used and any checks that were skipped

For GUI solves, look for the Flotherm message indicating that the steady solver
stopped after convergence. For result extraction, read
`base/reference/postprocessing.md`. For acceptance details, read
`base/reference/acceptance_checklists.md`.

## Load additional guidance only when needed

- FloSCRIPT modeling: `base/reference/floscript_modeling.md`
- Result extraction: `base/reference/postprocessing.md`
- Error-code triage: `base/reference/error_codes.md`
- Headless authoring limitations: `base/reference/headless_bootstrap_investigation.md`
- Runtime control patterns: `base/reference/runtime_patterns.md`
- Known driver and vendor issues: `known_issues.md`
- Release-specific differences: `solver/<detected-version>/notes.md`

The version-specific layer is useful only after the installed Flotherm release
has been detected. Do not assume a `/connect` response or active solver layer
exists before capability discovery.
