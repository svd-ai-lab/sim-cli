# Flotherm error code reference

Triage table for FloSCRIPT / solver / translator codes encountered in `WinXP\bin\LogFiles\logFile*.xml` and `floerror.log`. Read this when an `ok=false` result lands and you need to decide whether to retry, change inputs, or surface fatally.

> **Provenance.** Codes observed against Flotherm **2504**. The `E/` / `W/` / `I/` namespace is consistent across recent Simcenter Flotherm releases, but only 2504 was probed. If you're on `2406` / `2410` / `2412` / a later release and see a code not listed here, append it to this table — see "Refresh for another version" at the bottom.

## Severity convention

Flotherm prefixes diagnostic lines with `ERROR   E/<NNNNN>`, `WARN  W/<NNNNN>`, or `INFO    I/<NNNNN>` (note the variable whitespace — strip before regex matching). Codes are namespaced by the leading digits:

| Range | Subsystem |
|---|---|
| `6xxx` | Tables / CSV export |
| `9xxx` | Mesher / grid / domain |
| `11xxx` | Project lifecycle (load / lock / file-type) |
| `15xxx` | FloSCRIPT runtime (commands, properties, libraries, validation) |

## Where codes show up

1. **`<install>\WinXP\bin\LogFiles\logFile<timestamp>.xml`** — auto-recorded every GUI session, up to 5 retained. Each diagnostic appears as `<message text="ERROR …"/>`. Easiest channel for headless monitoring (file read; no UIA round-trip).
2. **`%FLOUSERDIR%\<project>\floerror.log`** — persistent per-project log. Some 11xxx codes (notably `E/11029`) are written **only** here, not to stderr.

The same code may appear in either or both channels. The driver's `lib/error_log.py` parses both `floerror.log` and the GUI XML logs; `tail_logfile_xml()` reads the most recent GUI log, and GUI playback responses surface new entries as `gui_log` / `gui_log_errors`.

## Catalogue

### `E/6xxx` — table / CSV export

| Code | Severity | Observed message | Condition | Driver action |
|---|---|---|---|---|
| `E/6000` | error | `Failed to export Tables CSV file` | `export_table` / `csv_export_attribute` targeted a row/attribute that doesn't resolve, or the destination path is unwritable. | Surface to caller; do not retry without changing inputs. If it follows a failed `project_load`, recommend `disconnect` + `connect`. |

### `E/9xxx` — mesher / grid

| Code | Severity | Observed message | Condition | Driver action |
|---|---|---|---|---|
| `I/9033` | info | `Total number of Grid Cells are: <N>` | Pre-flight count. **A value of `1` is diagnostic of `E/9012`.** | Log only; surface as a metric in `query_status()`. |
| `E/9012` | error | `Too few grid-cells to be solved NX = 1 and NY = 1` | Solver started against a project whose grid wasn't successfully built. Frequently downstream of `E/11029`. | Treat as fatal; correlate with the immediately preceding `E/11029`. Don't retry without a successful translator pass. |
| `I/9001` | info | `Solver stopped: steady solution converged` | Successful solve marker. | Required positive signal for `query_status()` to flip `ok=true`. |

### `E/11xxx` — project lifecycle

| Code | Severity | Observed message | Condition | Driver action |
|---|---|---|---|---|
| `E/11008` | error | `Failed to import …` | `<project_import>` was called with an `import_type` that doesn't match the GUI menu text — e.g. `"pack"` instead of `"Pack File"`. | Validate `import_type` ∈ {`"Pack File"`, `"FloXML"`, `"PDML"`, …} before dispatch; recommend re-emit with the canonical value. |
| `E/11013` | error | `Failed to get a lock: If project not already in use Select [Project/Load…/Unlock] to unlock` | A previous Flotherm session crashed leaving `group.lck` / `notes.lck`, or another process has the project open. | `<project_unlock project_name="…"/>` first, retry `<project_load>`. If repeated, fall back to `flounlock.exe -d <project>` from the shell. |
| `E/11029` | error | `Failed unknown file type No reader for this file type — <project_dir>` | `floserv.exe` fell through to the translator code path with the project directory name treated as a filename. **The defining symptom of the broken `flotherm.bat -b` flag (ISSUE-001).** | Don't go through `flotherm.bat -b`; use direct `translator.exe -p <project>` + `solexe.exe -p <project>`. Treat as fatal. |
| `E/11055` | error | `Cannot save using default project name DefaultSI` | `Solve > Solve` was triggered on the unsaved default project. Flotherm opens `Save Project`; accepting the default name fails, and the solve may continue far enough to emit downstream grid errors such as `E/9012`. | Treat as a project setup failure. Cancel/close the Save Project and Message Window UI, surface `gui_log_errors`, and require a real project name/import before retrying. |
| `E/15105` | error | `Failed to load project: <project_name>` | The project doesn't exist in `FLOUSERDIR`, or its `group.cat` / `PDProject` is corrupted. Often paired with `E/11013` when a stale lock blocks a re-load attempt. | If preceded by `E/11013`, retry after `<project_unlock>`. Otherwise treat as fatal; verify the project directory exists and contains `PDProject/group`. |

### `E/15xxx` — FloSCRIPT runtime

| Code | Severity | Observed message | Condition | Driver action |
|---|---|---|---|---|
| `E/15000` | error | `Command failed to find Attribute: <attribute>` | A command (`modify_attribute`, `csv_export_attribute`, …) referenced an attribute name that doesn't exist on the active project. | Surface; do not retry. Caller can verify with `<find>` + `<commonStringQueryConstraint>`. |
| `E/15001` | error | `Command failed to find library node` | `<load_from_library>` was passed a `<library_name>` path that doesn't resolve. **Open question** — see ISSUE-006 in `known_issues.md`. | Surface; do not retry. Workaround: build attributes by hand with `<create_attribute>` + `<modify_attribute>`. |
| `E/15002` | error | `Command failed to find property: <name>` | `modify_attribute` / `modify_geometry` / `modify_solver_control` was given a `property_name` the runtime doesn't recognise. The XSD declares `property_name` as `xs:string` so structural lint passes — only Flotherm catches it at runtime. **See ISSUE-005**. | Surface; do not retry. Always pair with the immediately following `W/15000` to confirm the script aborted. Suggest the recording-oracle workflow. |
| `E/15013` | error | `FloSCRIPT validation error: <reason> On line <N>` | The submitted FloSCRIPT failed schema validation. Common causes: PCDATA in an empty element, unknown command name, missing required attribute. | The driver should validate locally (`lib/floscript.py:_validate_xsd()`) before dispatch — anything reaching this code is a driver bug or a hand-edited script. Surface with the line number. |
| `W/15000` | warning | `Aborting XML due to previous error` | Companion warning that **always** follows a fatal `E/15xxx` to indicate the rest of the script was dropped. | Use as a positive signal that the script abort happened cleanly; absence after an `E/15xxx` is suspicious (Flotherm may still be running residual commands). |

### Vendor-documented but not yet observed live

These appear in the FloSCRIPT v11 tutorial / examples but haven't been observed in our 2504 sessions yet:

- `E/15014` — FloSCRIPT validation error variants (different reason than `15013`).
- `E/15100..15110` range — project lifecycle variants beyond `E/15105`.

If you see one on the wire, append a row above with the exact message you observed.

## Parsing recipe

Both channels can be parsed with the same regex. For the GUI log XML:

```python
import re
from xml.etree import ElementTree as ET

CODE_RE = re.compile(r"\b([EWI])/(\d+)\s*-?\s*(.*)")
SEVERITY = {"E": "error", "W": "warning", "I": "info"}

def parse_logfile_xml(path):
    """Yield (severity, code_int, code_full, message) for each <message text=…/>
    in a Flotherm WinXP/bin/LogFiles/logFile*.xml file."""
    tree = ET.parse(path)
    for el in tree.getroot().iter("message"):
        text = (el.get("text") or "").strip()
        for token in text.split():
            m = CODE_RE.match(token)
            if m:
                severity = SEVERITY[m.group(1)]
                code_int = int(m.group(2))
                rest = text.split(token, 1)[1].lstrip(" -")
                yield severity, code_int, f"{m.group(1)}/{m.group(2)}", rest
                break
```

For `floerror.log` the same regex works against each line (no XML envelope).

The driver's `lib/error_log.py` parser is used by both `parse_error_log()` for `floerror.log` and `tail_logfile_xml()` for GUI session logs. `play_floscript()` baselines the GUI log before playback and reports only newly observed entries for that run.

## Refresh for another version

The error code namespace is stable across recent Flotherm releases per Siemens convention, but re-snapshot whenever you switch hosts:

```powershell
$ver = '<version>'
$logs = "C:\Program Files\Siemens\SimcenterFlotherm\$ver\WinXP\bin\LogFiles"
Get-ChildItem $logs -Filter '*.xml' |
  ForEach-Object { Get-Content $_.FullName } |
  Select-String -Pattern '[EWI]/\d+' |
  ForEach-Object { ($_ -split '\s+' | Where-Object { $_ -match '^[EWI]/\d+' })[0] } |
  Sort-Object -Unique
```

Compare the resulting set against the codes in this doc. Append rows for new ones. Don't speculate on the condition — only describe what you actually saw.

## See also

- Full FloSCRIPT command catalogue (620 commands, 6 schema roots): [`sim-proj/dev-docs/flotherm/floscript_catalog.md`](https://github.com/svd-ai-lab/sim-proj/blob/main/dev-docs/flotherm/floscript_catalog.md)
- `known_issues.md` for the issue-tracker view (ISSUE-001 through ISSUE-006 cross-reference these codes)
- `headless_bootstrap_investigation.md` for the open `E/15001` library-path question
