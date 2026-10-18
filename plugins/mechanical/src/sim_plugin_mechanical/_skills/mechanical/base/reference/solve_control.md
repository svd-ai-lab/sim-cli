# Solve control

## Triggering a solve

```python
analysis = Model.Analyses[0]
analysis.Solution.Solve(True)  # True = wait for solve to finish
# After return:
status = str(analysis.Solution.Status)
# One of: "Done", "Failed", "SolveRequired", "NotSolved"
```

Prefer solving through `analysis.Solution`; official PyMechanical examples use
that object, and result evaluation state follows it. `Solve(False)` is
non-blocking but **you cannot exit the session** while a solve is in progress.
Use blocking.

## Pre-solve validation

```python
from MechanicalEnums.Common import MessageSeverityType

# Check for errors before the long solve
msgs = ExtAPI.Application.Messages
errors  = [m for m in msgs if m.Severity == MessageSeverityType.Error]
warns   = [m for m in msgs if m.Severity == MessageSeverityType.Warning]

if errors:
    # bail out
    raise Exception("pre-solve errors: " + "; ".join(str(e.DisplayString) for e in errors))
```

Before solving a workflow that differs from the local snippets, confirm the
live analysis, setup, and result APIs:

```bash
uv run sim inspect mechanical.capabilities:analysis:0
```

## Monitoring from outside the gRPC call

`Solve(True)` blocks the gRPC thread. While it blocks:

- sim's `exec` is blocked.
- sim's `screenshot` still works (independent HTTP path).
- You can tail the `solver.out` file in the working directory via
  `mech.list_files()` + `mech.download(...)`.

Pattern for progress polling (from a different process/terminal):

```bash
# Terminal A: kick off solve
uv run sim exec "Model.Analyses[0].Solution.Solve(True)"   # blocks until done

# Terminal B: poll
while true; do
  uv run sim screenshot -o /tmp/solve_progress_$(date +%s).png
  sleep 10
done
```

## Solve settings

```python
settings = Model.Analyses[0].AnalysisSettings

# Step controls
settings.NumberOfSteps = 1
settings.CurrentStepNumber = 1

# Auto time step
settings.AutomaticTimeStepping = AutomaticTimeStepping.On
settings.InitialTimeStep = Quantity("0.1 [s]")
settings.MinimumTimeStep = Quantity("0.001 [s]")
settings.MaximumTimeStep = Quantity("1 [s]")

# Output controls (what gets saved)
settings.NodalForces = OutputControlsNodalForces.Yes
settings.StressResult = True
settings.StrainResult = True
```

## Solver selection

```python
# Direct, Iterative, Program Controlled
settings.SolverType = SolverType.Direct

# Large deflection
settings.LargeDeflection = True
```

## Solve process settings

When the solver module fails to start, inspect and simplify the solve handler
before changing model physics. Official Mechanical scripting examples use
`ExtAPI.Application.SolveConfigurations[...]` and set
`SolveProcessSettings.MaxNumberOfCores` before `Solution.Solve(True)`.

```python
config = ExtAPI.Application.SolveConfigurations["My Computer, Background"]
config.SetAsDefault()
config.SolveProcessSettings.MaxNumberOfCores = 1
Model.Analyses[0].Solution.Solve(True)
```

Use the live `SolveConfigurations` collection to choose an available local
configuration; do not assume every installation has the same handler names.

## Reading solve messages

```python
msgs = Model.Analyses[0].Solution.Messages
for m in msgs:
    print(m.Severity, m.DisplayString)
```

## Common failures

| Symptom | Root cause | Fix |
|---|---|---|
| `"pre-solve errors: ... contact"` | Missing contacts | Auto-detect contacts or add manually |
| `"Solution did not converge"` | Non-linear + small load steps | Increase `MinimumTimeStep`, enable `AutoTimeStepping` |
| Solve hangs at 0% | Solver startup did not complete | Inspect `session.health`, solver artifacts, and retry from a fresh session |
| Post-processing dialog says a result cannot be loaded | Solve did not complete, result file is missing/stale, or result type is incompatible | Inspect `Solution.Status`, `mechanical.messages`, and solver files before adding more result objects |
| `"Element formulation incompatible"` | Mixed 2D/3D bodies | Suppress one body or change element type |
