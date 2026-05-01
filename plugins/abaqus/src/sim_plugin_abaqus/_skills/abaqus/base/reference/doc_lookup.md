# Abaqus Documentation Lookup

Use this workflow whenever the agent is uncertain about an Abaqus keyword,
CAE Python object, method signature, command-line option, output variable, or
solver diagnostic. Do not guess Abaqus APIs when the cost of a wrong command is
a failed model build.

## Source Order

1. **Bundled skill references** for common patterns already captured in this
   plugin: input deck syntax, CAE scripting, authoring workflow, diagnostics,
   and analysis type selection.
2. **Installed Abaqus help** when available on the host. The command-line
   help lists execution procedures, and the documentation launcher opens the
   installed HTML documentation if it has been configured.
3. **Official SIMULIA documentation portal** when the user has access. Use the
   Abaqus Scripting Reference Guide for object and method signatures, the
   Keywords Guide for `.inp` syntax, and the Execution Guide for command-line
   options.
4. **Abaqus runtime introspection** inside `sim exec` or
   `sim run --solver abaqus probe.py` for final verification of object
   availability and accepted arguments.

## Command-Line Discovery

Use these probes before relying on memory:

```powershell
sim check abaqus
abaqus help
abaqus doc
abaqus fetch job=<example-name>
abaqus information=release
```

Notes:

- `abaqus help` is safe for text discovery and lists available execution
  procedures, including `doc`, `fetch`, `cae`, `viewer`, and
  `information=...`.
- `abaqus doc` opens the installed HTML documentation in a browser. Use it
  when a human or browser-capable environment is available; do not rely on it
  in headless automation.
- `abaqus fetch` retrieves installed example input files or scripts by job
  name. Use fetched examples as reference material, not as unquestioned
  templates.
- `abaqus information=release` is a low-risk way to confirm the active
  release. Avoid recording host, license, user, network, or machine details in
  public logs or reports.

## Runtime Introspection

When a method or repository name is uncertain, run a tiny noGUI or bridge
snippet and inspect the object rather than inventing a call:

```python
model = mdb.models["Model-1"]
_sim_result = {
    "model_attrs": [name for name in dir(model) if "Section" in name],
    "part_repo_type": type(model.parts).__name__,
    "material_methods": [name for name in dir(model.Material(name="DocProbe")) if "Elastic" in name],
}
```

For constructor or method signatures, try a minimal object in an isolated
workspace, catch exceptions, and keep the snippet small. Clean up probe objects
or use distinctive names such as `DocProbe*` so they are easy to remove.

## What To Verify

For CAE Python:

- Repository paths: `mdb.models[...]`, `model.parts[...]`,
  `model.rootAssembly.instances[...]`.
- Object creation methods and required arguments.
- Whether constants come from `abaqusConstants`.
- Whether a method mutates `mdb`, `session`, an ODB, or only the viewport.
- Whether the call is available in noGUI mode.

For input decks:

- Keyword spelling and required suboptions.
- Required data line order and units.
- Step compatibility, element compatibility, and output request names.
- Whether the keyword is Standard-only, Explicit-only, or shared.

For command-line execution:

- Whether the option belongs to `abaqus job=...`, `abaqus cae`, `abaqus viewer`,
  or another execution procedure.
- Whether a command writes files in the current working directory.
- Whether arguments must be passed after `--` for CAE scripts.

## Report Evidence

When documentation lookup affects the model, include a concise note in the
debug/report trail:

- What was checked: guide name, command help, fetched example, or runtime
  probe.
- The decision made from it: keyword, API method, element choice, output
  request, or command option.
- Any remaining assumption that the user should review.

Do not paste long proprietary documentation excerpts into repo files or public
comments. Summarize the verified behavior and link or cite the source when the
environment permits.

## Failure Modes

- If `abaqus doc` cannot open documentation, fall back to the official portal
  or runtime introspection.
- If online docs require authentication, ask the user for access or use local
  installed help/fetched examples.
- If `dir()` shows a method but a call fails, trust the exception and test a
  smaller minimal call before editing the real model.
- If examples differ from the active release, prefer the active release docs
  and a local runtime probe.
