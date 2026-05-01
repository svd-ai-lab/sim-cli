# Abaqus Debugging and Reporting

Agent work is not complete when Abaqus exits. Treat solver completion as one
signal, then verify the model and results against engineering criteria.

## Debug Sources

Inspect these outputs after every job:

| File | Purpose | What to look for |
|---|---|---|
| `.msg` | Solver messages | errors, warnings, convergence problems, contact issues |
| `.sta` | Step/increment status | completed increments, cutbacks, aborts |
| `.dat` | Text results and summaries | requested nodal/element output, warnings |
| `.odb` | Binary result database | field outputs for reporting plots and extrema |
| `.com` | Command echo | job options and command context |

Use the mode closest to where the job state lives:

| Mode | Pick when | Recipe |
|---|---|---|
| Live | The solve is in progress or an Abaqus session is already open. This wins on Windows hosts because there is no portable streaming-tail alternative. | `sim inspect job.diagnostics` and `sim inspect workdir.files` |
| Post-mortem | The job finished and the files are on disk. | Use Python stdlib text parsing locally against fetched files. Prefer `uv run python ...` when uv is available; otherwise use the user's chosen Python environment. |

Host-side parsing and plotting should follow the sim-cli Python-helper
environment guidance. In cookbook repos, prefer uv when available because it
makes temporary dependencies explicit:

```powershell
uv run python parse_status.py
uv run --with matplotlib python plot_results.py
```

Avoid assuming bare `python` has matplotlib or other helper dependencies. If uv
is unavailable, use the interpreter/environment the user normally uses. Abaqus
ODB access is the exception: run ODB readers through `sim run --solver abaqus
odb_reader.py` so Abaqus launches its own embedded Python.

```python
from pathlib import Path
import re

p = "job.msg"
msg = Path(p).read_text(errors="replace")
errors = re.findall(r"^\s*\*+\s*ERROR.*", msg, re.M)
print("\n".join(errors))
```

## Debug Loop

1. Classify the failure: modeling error, missing set/surface, material/section
   issue, mesh quality, contact, convergence, license/environment, or
   post-processing.
2. Fix the smallest model element that explains the failure.
3. Re-inspect the model summary before rerunning.
4. Rerun and compare diagnostics against the previous attempt.
5. Record what changed and why in the final report.

## Report Checklist

A usable Abaqus report should include:

- Objective and acceptance criteria.
- Unit system and coordinate conventions.
- Geometry/parts, materials, sections, and element types.
- Boundary conditions, loads, contacts/interactions, and analysis steps.
- Mesh summary and any mesh-quality caveats.
- Solver status: completed/failed, key warnings/errors, increments/cutbacks.
- Result quantities tied to acceptance criteria.
- Engineering interpretation: pass/fail, margin, and dominant assumptions.
- Reproducibility: input deck or CAE script path, job name, and output files.

## Report Tone

Be explicit about uncertainty. If a result is only a coarse smoke, call it a
coarse smoke. If convergence warnings remain, do not present the result as a
validated design result.
