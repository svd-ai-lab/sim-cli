# FloSCRIPT Modeling Reference

> **⚠️ FOR AUTHORING NEW MODELS: USE FLOXML, NOT FLOSCRIPT.**
> FloSCRIPT was designed as a record-and-replay format, not as an
> authoring API. The `<create_geometry>` / `<create_attribute>` /
> `<modify_attribute>` patterns mostly **do not work** for non-trivial
> properties — their `property_name` enums are undocumented internals.
>
> See **[`floxml_authoring.md`](floxml_authoring.md)** for the
> vendor-blessed `<xml_case>` authoring format — fully exemplified in
> the install's `examples/FloXML/`, and verified end-to-end on
> Flotherm 2504 (HBM smoke test, 2026-04-18).
>
> **Use FloSCRIPT for:** parametric sweeps over an imported `.pack`
> (`<modify_geometry property_name="power" new_value="20"/>` works for
> `pcbComponent`/`die` with intrinsic numeric properties), solve
> orchestration (`<start start_type="solver"/>`, `<project_save_as>`,
> `<project_load>`, `<project_import filename="..." import_type="FloXML"/>`),
> and result extraction triggers.

---

Generate Flotherm models from natural language by producing FloSCRIPT
XML that `uv run sim exec` plays step by step. Each step is a separate file
validated via `uv run sim lint` before playback.

## Workflow

```
uv run sim connect --solver flotherm --ui-mode gui
# For each step:
#   1. Generate stepN.xml
#   2. sim lint stepN.xml          ← XSD validates automatically
#   3. uv run sim exec stepN.xml          ← plays in Flotherm GUI
#   4. sim screenshot              ← verify visually
# When done:
uv run sim disconnect
```

## Step Template

Every step file must follow this structure:

```xml
<?xml version="1.0"?>
<xml_log_file version="1.0">
    <!-- modeling commands here -->

    <!-- checkpoint (use incrementing names) -->
    <project_save_as project_name="model_stepN"
                     project_title="Description of what this step did"/>
</xml_log_file>
```

## Crash Recovery

If the session dies mid-build, reload from the last checkpoint:

```xml
<xml_log_file version="1.0">
    <project_load project_name="model_step2"/>
    <!-- continue from step 3 -->
</xml_log_file>
```

---

## Full command catalogue

The patterns below cover the day-to-day modeling vocabulary. For the **complete** list of FloSCRIPT commands — 620 direct commands across 6 schema roots (`xml_log_file`, `cc_xml_log_file`, `eda_xml_log_file`, `floviz_xml_log_file`, `flopack_xml_log_file`, `mcad_xml_log_file`) plus 237 complex types — see the catalogue in sim-proj:

[`sim-proj/dev-docs/flotherm/floscript_catalog.md`](https://github.com/svd-ai-lab/sim-proj/blob/main/dev-docs/flotherm/floscript_catalog.md)

Use it when the patterns here don't have what you need (e.g. `csv_export_attribute`, `start_record_script`, `refresh_library`, `project_run_script`). Each entry lists the command name and its XSD complex-type so you can grep the schema for the attribute set.

## Script chaining: `project_run_script` (verified on 2504)

`<project_run_script file_name="…"/>` runs another FloSCRIPT from inside the running script context. **Verified on Flotherm 2504 (2026-04-27)** — see "Verification" below for the probe artifacts. This collapses N `Macro → Play FloSCRIPT` clicks into one orchestrator script:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<xml_log_file version="1.0">
  <project_load project_name="my_project"/>
  <project_run_script file_name="step_01_geometry.xml"/>
  <project_run_script file_name="step_02_solve.xml"/>
  <project_run_script file_name="step_03_export.xml"/>
  <quit/>
</xml_log_file>
```

The outer orchestrator still needs **one** GUI invocation (Macro → Play FloSCRIPT, automated by sim-cli's UIA driver). After that, every `<project_run_script>` runs in-process; no further UI clicks required. `<quit/>` is the FloSCRIPT primitive to close Flotherm cleanly at the end — also verified to work in playback.

`project_run_script` is available in all 7 schema roots — surfaced via [lixiekun/flotherm-automation#1](https://github.com/lixiekun/flotherm-automation/issues/1#issuecomment-4324008578) (2026-04-27).

### Verification (Flotherm 2504, 2026-04-27)

Three independent probes settled the question:

1. **`<quit/>`-only probe.** A 1-command orchestrator with just `<quit/>`. Flotherm GUI closes after play. Confirms `<quit>` works in playback.
2. **Typo probe.** Outer calls inner via `<project_run_script>`; inner has a deliberate XSD-invalid `<start_record_script filename="…"/>` (wrong attribute name — should be `file_name`). The GUI session log captured `E/15013 - FloSCRIPT validation error: attribute 'filename' is not declared … On line 3` — and **line 3 is in the inner script**. Flotherm parsed and validated the inner, which would not happen if `<project_run_script>` were record-only.
3. **Inner-quit probe.** Outer calls inner via `<project_run_script>`; inner contains only `<quit/>`. After play, the `flomain` GUI process is gone (only `floserv`/`floview` remain). Since the outer has no `<quit/>`, the close came from the inner — final confirmation that the chain runs in-process.

The "schema-valid but runtime-no-op" risk that sank `<load_from_library>` (ISSUE-006) and `flotherm.bat -f` (ISSUE-003) doesn't apply here.

### Caveats from verification

- **`<project_load project_name="…"/>` requires the project to already be registered in `group.cat`** (per the canonical `base/workflows/solve_mobile_demo.xml` note). Loading a brand-new project from a fresh `uv run sim connect` session produces `E/15105 - Failed to load project`. If you want the orchestrator to load a project, use `<project_import>` first or pre-register via the GUI.
- **The driver's `ok` flag flips false on `<quit/>`-bearing scripts** because Flotherm closes underneath the session. Expected — re-`connect` for follow-up commands.

## Error triage

When playback fails, runtime errors land in the Message Window dock and `floerror.log`. The catalogue of every `E/<NNNNN>` / `W/<NNNNN>` / `I/<NNNNN>` code observed on 2504, with severity, message template, condition, and suggested driver action, is in [`error_codes.md`](error_codes.md). Read it before retrying a failed `uv run sim exec`.

## Command Reference

### Create geometry

```xml
<create_geometry geometry_type="TYPE">
    <source_geometry>
        <geometry name="PARENT_ASSEMBLY"/>
    </source_geometry>
</create_geometry>
```

**Common geometry types** (full list in XSD schema):

| Type | Use for |
|---|---|
| `cuboid` | Generic block, board, wall, enclosure wall |
| `source` | Heat source (power dissipation) |
| `fan` | Axial or radial fan |
| `heatSink` | Finned heat sink |
| `pcb` | Printed circuit board (with layers) |
| `pcbComponent` | Component on PCB |
| `enclosure` | Box/chassis around components |
| `cylinder` | Round geometry (pipes, posts) |
| `resistance` | Thermal interface material (TIM) |
| `monitorPoint` | Temperature probe point |
| `assembly` | Grouping container |
| `hole` | Ventilation opening in enclosure |
| `cooler` | Liquid cooling block |
| `heatPipe` | Heat pipe |
| `tec` | Thermoelectric cooler |
| `die` | Semiconductor die (with discrete sources) |
| `rack` | Equipment rack |

### Rename geometry

Rename immediately after create — default names are generic (`Cuboid`, `Source`, etc.).

```xml
<rename_geometry new_name="MyChip">
    <geometry_name>
        <geometry name="Root Assembly">
            <geometry name="Source" position_in_parent="INDEX"/>
        </geometry>
    </geometry_name>
</rename_geometry>
```

### Modify geometry

Set size, position, material, power, or any property:

```xml
<modify_geometry new_value="VALUE" property_name="PROPERTY">
    <geometry_name>
        <geometry name="Root Assembly">
            <geometry name="MyChip" position_in_parent="INDEX"/>
        </geometry>
    </geometry_name>
</modify_geometry>
```

**Common properties:**

> **⚠ Many property names in this table are UNVERIFIED against Flotherm 2504.**
> The XSD declares `property_name` as `xs:string` — bad names pass `uv run sim lint`
> and only fail at runtime with `ERROR E/15002 - Command failed to find property`.
> Verified on 2026-04-17: `sizeX/Y/Z` and `positionX/Y/Z` work on both `cuboid`
> and `source`. Everything else below should be confirmed by recording FloSCRIPT
> in the GUI (`Macro → Record FloSCRIPT`) before relying on it.

| Property | Applies to | Example | Status (2504) |
|---|---|---|---|
| `sizeX`, `sizeY`, `sizeZ` | All geometry | `"0.05"` (meters) | ✓ verified |
| `positionX`, `positionY`, `positionZ` | All geometry | `"0.01"` | ✓ verified |
| `material` | cuboid, resistance | `"Aluminum"` | ✗ REJECTED E/15002 |
| `power` | source | `"5.0"` (watts) | ✗ REJECTED E/15002 |
| `finHeight` | heatSink | `"0.02"` | unverified |
| `numberOfFins` | heatSink | `"12"` | unverified |
| `finThickness` | heatSink | `"0.001"` | unverified |
| `flowRate` | fan | `"0.01"` (m³/s) | unverified |
| `conductivity` | resistance | `"5.0"` (W/m·K) | unverified |

For setting material and power, the correct path is likely `<create_attribute>` + attach-to-geometry (not direct `modify_geometry`) — syntax to be confirmed by GUI-recording.

### Create attribute

Attributes control grid, materials, boundary conditions, etc.:

```xml
<create_attribute attribute_type="TYPE" id="ATTR_NAME"/>
```

**Attribute types:** `ambient`, `control`, `fluid`, `gridConstraint`,
`material`, `occupancy`, `radiation`, `resistance`, `source`, `surface`,
`surfaceExchange`, `thermal`, `transient`

### Modify attribute

```xml
<modify_attribute new_value="VALUE" property_name="PROPERTY">
    <attribute_name id="ATTR_NAME"/>
</modify_attribute>
```

### Delete geometry

```xml
<delete_geometry>
    <geometry_name>
        <geometry name="Root Assembly">
            <geometry name="OldPart" position_in_parent="INDEX"/>
        </geometry>
    </geometry_name>
</delete_geometry>
```

### Save project

```xml
<project_save_as project_name="NAME" project_title="TITLE"/>
```

### Solve

```xml
<start start_type="solver"/>
```

---

## Geometry Naming and `position_in_parent`

**Critical:** `position_in_parent` is a 0-based index within the parent
assembly, assigned in creation order. When you create the 3rd object
under `Root Assembly`, it gets `position_in_parent="2"`.

**Best practice:**
1. Create geometry → immediately rename to a meaningful name
2. Reference by name (not index) in subsequent steps
3. After renaming, use the new name in the `<geometry name="...">` path

```xml
<!-- Step 1: Create and rename -->
<create_geometry geometry_type="cuboid">
    <source_geometry><geometry name="Root Assembly"/></source_geometry>
</create_geometry>
<rename_geometry new_name="BoardBase">
    <geometry_name>
        <geometry name="Root Assembly">
            <geometry name="Cuboid" position_in_parent="0"/>
        </geometry>
    </geometry_name>
</rename_geometry>

<!-- Step 1 continued: modify using the renamed name -->
<modify_geometry new_value="0.1" property_name="sizeX">
    <geometry_name>
        <geometry name="Root Assembly">
            <geometry name="BoardBase" position_in_parent="0"/>
        </geometry>
    </geometry_name>
</modify_geometry>
```

**Important:** Even after renaming, you still need
`position_in_parent` in the path. The name changes but the index
doesn't.

---

## Common Patterns

### PCB with chip and heat sink

```xml
<xml_log_file version="1.0">
    <!-- PCB: 100mm × 80mm × 1.6mm -->
    <create_geometry geometry_type="pcb">
        <source_geometry><geometry name="Root Assembly"/></source_geometry>
    </create_geometry>
    <rename_geometry new_name="MainPCB">
        <geometry_name>
            <geometry name="Root Assembly">
                <geometry name="PCB" position_in_parent="0"/>
            </geometry>
        </geometry_name>
    </rename_geometry>
    <modify_geometry new_value="0.1" property_name="sizeX">
        <geometry_name>
            <geometry name="Root Assembly">
                <geometry name="MainPCB" position_in_parent="0"/>
            </geometry>
        </geometry_name>
    </modify_geometry>
    <modify_geometry new_value="0.08" property_name="sizeY">
        <geometry_name>
            <geometry name="Root Assembly">
                <geometry name="MainPCB" position_in_parent="0"/>
            </geometry>
        </geometry_name>
    </modify_geometry>

    <!-- Chip: 10mm × 10mm × 2mm, 5W, centered on PCB -->
    <create_geometry geometry_type="source">
        <source_geometry><geometry name="Root Assembly"/></source_geometry>
    </create_geometry>
    <rename_geometry new_name="Chip">
        <geometry_name>
            <geometry name="Root Assembly">
                <geometry name="Source" position_in_parent="1"/>
            </geometry>
        </geometry_name>
    </rename_geometry>
    <modify_geometry new_value="0.01" property_name="sizeX">
        <geometry_name>
            <geometry name="Root Assembly">
                <geometry name="Chip" position_in_parent="1"/>
            </geometry>
        </geometry_name>
    </modify_geometry>
    <modify_geometry new_value="0.01" property_name="sizeY">
        <geometry_name>
            <geometry name="Root Assembly">
                <geometry name="Chip" position_in_parent="1"/>
            </geometry>
        </geometry_name>
    </modify_geometry>
    <modify_geometry new_value="0.002" property_name="sizeZ">
        <geometry_name>
            <geometry name="Root Assembly">
                <geometry name="Chip" position_in_parent="1"/>
            </geometry>
        </geometry_name>
    </modify_geometry>
    <modify_geometry new_value="0.045" property_name="positionX">
        <geometry_name>
            <geometry name="Root Assembly">
                <geometry name="Chip" position_in_parent="1"/>
            </geometry>
        </geometry_name>
    </modify_geometry>
    <modify_geometry new_value="0.035" property_name="positionY">
        <geometry_name>
            <geometry name="Root Assembly">
                <geometry name="Chip" position_in_parent="1"/>
            </geometry>
        </geometry_name>
    </modify_geometry>
    <modify_geometry new_value="0.0016" property_name="positionZ">
        <geometry_name>
            <geometry name="Root Assembly">
                <geometry name="Chip" position_in_parent="1"/>
            </geometry>
        </geometry_name>
    </modify_geometry>
    <modify_geometry new_value="5.0" property_name="power">
        <geometry_name>
            <geometry name="Root Assembly">
                <geometry name="Chip" position_in_parent="1"/>
            </geometry>
        </geometry_name>
    </modify_geometry>

    <!-- Heat sink: 30mm × 30mm, on top of chip -->
    <create_geometry geometry_type="heatSink">
        <source_geometry><geometry name="Root Assembly"/></source_geometry>
    </create_geometry>
    <rename_geometry new_name="HS1">
        <geometry_name>
            <geometry name="Root Assembly">
                <geometry name="Heat Sink" position_in_parent="2"/>
            </geometry>
        </geometry_name>
    </rename_geometry>
    <modify_geometry new_value="0.03" property_name="sizeX">
        <geometry_name>
            <geometry name="Root Assembly">
                <geometry name="HS1" position_in_parent="2"/>
            </geometry>
        </geometry_name>
    </modify_geometry>
    <modify_geometry new_value="0.03" property_name="sizeY">
        <geometry_name>
            <geometry name="Root Assembly">
                <geometry name="HS1" position_in_parent="2"/>
            </geometry>
        </geometry_name>
    </modify_geometry>
    <modify_geometry new_value="0.04" property_name="positionX">
        <geometry_name>
            <geometry name="Root Assembly">
                <geometry name="HS1" position_in_parent="2"/>
            </geometry>
        </geometry_name>
    </modify_geometry>
    <modify_geometry new_value="0.025" property_name="positionY">
        <geometry_name>
            <geometry name="Root Assembly">
                <geometry name="HS1" position_in_parent="2"/>
            </geometry>
        </geometry_name>
    </modify_geometry>
    <modify_geometry new_value="0.0036" property_name="positionZ">
        <geometry_name>
            <geometry name="Root Assembly">
                <geometry name="HS1" position_in_parent="2"/>
            </geometry>
        </geometry_name>
    </modify_geometry>

    <!-- Monitor point at chip center -->
    <create_geometry geometry_type="monitorPoint">
        <source_geometry><geometry name="Root Assembly"/></source_geometry>
    </create_geometry>
    <modify_geometry new_value="0.05" property_name="positionX">
        <geometry_name>
            <geometry name="Root Assembly">
                <geometry name="Monitor Point" position_in_parent="3"/>
            </geometry>
        </geometry_name>
    </modify_geometry>
    <modify_geometry new_value="0.04" property_name="positionY">
        <geometry_name>
            <geometry name="Root Assembly">
                <geometry name="Monitor Point" position_in_parent="3"/>
            </geometry>
        </geometry_name>
    </modify_geometry>
    <modify_geometry new_value="0.003" property_name="positionZ">
        <geometry_name>
            <geometry name="Root Assembly">
                <geometry name="Monitor Point" position_in_parent="3"/>
            </geometry>
        </geometry_name>
    </modify_geometry>

    <project_save_as project_name="pcb_chip_hs"
                     project_title="PCB with chip source and heat sink"/>
</xml_log_file>
```

### Enclosure with fan (natural convection + forced air)

```xml
<xml_log_file version="1.0">
    <!-- Enclosure: 200mm × 150mm × 50mm -->
    <create_geometry geometry_type="enclosure">
        <source_geometry><geometry name="Root Assembly"/></source_geometry>
    </create_geometry>
    <rename_geometry new_name="Chassis">
        <geometry_name>
            <geometry name="Root Assembly">
                <geometry name="Enclosure" position_in_parent="0"/>
            </geometry>
        </geometry_name>
    </rename_geometry>
    <modify_geometry new_value="0.2" property_name="sizeX">
        <geometry_name>
            <geometry name="Root Assembly">
                <geometry name="Chassis" position_in_parent="0"/>
            </geometry>
        </geometry_name>
    </modify_geometry>
    <modify_geometry new_value="0.15" property_name="sizeY">
        <geometry_name>
            <geometry name="Root Assembly">
                <geometry name="Chassis" position_in_parent="0"/>
            </geometry>
        </geometry_name>
    </modify_geometry>
    <modify_geometry new_value="0.05" property_name="sizeZ">
        <geometry_name>
            <geometry name="Root Assembly">
                <geometry name="Chassis" position_in_parent="0"/>
            </geometry>
        </geometry_name>
    </modify_geometry>

    <!-- Fan at inlet -->
    <create_geometry geometry_type="fan">
        <source_geometry><geometry name="Root Assembly"/></source_geometry>
    </create_geometry>
    <rename_geometry new_name="InletFan">
        <geometry_name>
            <geometry name="Root Assembly">
                <geometry name="Fan" position_in_parent="1"/>
            </geometry>
        </geometry_name>
    </rename_geometry>

    <project_save_as project_name="chassis_fan"
                     project_title="Enclosure with inlet fan"/>
</xml_log_file>
```

---

## Pitfalls

1. **Units are always SI** (meters, watts, kg, K). No unit conversion —
   `sizeX="0.01"` means 10 mm.

2. **Default names vary by type.** `cuboid` → `"Cuboid"`, `source` →
   `"Source"`, `heatSink` → `"Heat Sink"` (with space), `fan` → `"Fan"`,
   `pcb` → `"PCB"`, `monitorPoint` → `"Monitor Point"`.
   When creating a second of the same type, Flotherm appends `:1`
   (e.g. `"Cuboid:1"`).

3. **`position_in_parent` is required** even when referencing by name.
   It's the creation order index (0-based) under the parent assembly.

4. **Lint before play.** `uv run sim lint stepN.xml` catches typos in
   geometry_type, unknown commands, and structural errors — with line
   numbers. Fix all errors before `uv run sim exec`.

5. **One step per file** for the iterate loop. Don't put the entire
   model in one file — if step 5 fails, you'd have to regenerate
   everything.

6. **Always `project_save_as` at the end of each step** so you have a
   checkpoint to recover from.

7. **XML comments are allowed** inside `<xml_log_file>` and are useful
   for documenting what each section does.

---

## Schema is structural only — check GUI-log errors after playback

**Critical gotcha:** `uv run sim lint` validates the XSD, but the XSD declares
`property_name` as `xs:string` — any string passes. Flotherm validates the
actual property names at **runtime**, and on rejection writes the error to
both the GUI session log and a dock widget inside the main window:

```
ERROR E/15002 - Command failed to find property: <name>
WARN  W/15000 - Aborting XML due to previous error
```

Recent driver versions surface newly observed GUI log entries in the `uv run sim exec`
response under `gui.gui_log` and `gui.gui_log_errors`; those are the primary
error channel. `dismissed_popups` can still be empty because the Message Window
is a `flohelp::DockWidget` embedded in `FloMainWindow`, not a top-level
`Window`. If the structured GUI log is inconclusive, read the dock manually.

### Reading the Message Window dock via UIA

After any FloSCRIPT exec, run this `#!python` probe to dump the dock's contents:

```python
#!python
import subprocess, sys
code = r'''
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from pywinauto import Desktop
main = next((w for w in Desktop(backend="uia").windows()
             if w.class_name() == "FloMainWindow"), None)
if not main: sys.exit("no FloMainWindow")
dock = next((d for d in main.descendants(control_type="Window")
             if "Message Window" in (d.window_text() or "")), None)
if not dock: sys.exit("no Message Window dock")
seen = set()
for d in dock.descendants():
    t = (d.window_text() or "").strip()
    if ("ERROR" in t or "WARN" in t) and t not in seen:
        seen.add(t); print(t)
'''
proc = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=30)
_result = proc.stdout.decode("utf-8", errors="replace")
```

Returns all `ERROR` / `WARN` lines currently in the dock. The dock accumulates
across runs — clear it via the "Clear" button if you want per-run isolation.

### Partial-execution gotcha

When Flotherm aborts on E/15002, commands that played BEFORE the bad line
are already applied (renames, creates, size/position changes). Re-running
from the top without clearing state produces duplicate geometry.
Either `uv run sim disconnect` + reconnect, or `<delete_geometry>` the previous
artifacts, before retrying.

---

## Probing for correct property names

When the doc doesn't match Flotherm, or you're exploring a new command,
test candidates rapid-fire via `#!python`:

```python
#!python
import os, subprocess, sys, time
TMP = r"C:\tmp\probe"; os.makedirs(TMP, exist_ok=True)

# Candidates to test — from most-likely to least
candidates = ["value", "power", "totalValue", "dissipation",
              "heatDissipation", "totalHeatDissipation"]

results = []
for i, prop in enumerate(candidates):
    path = os.path.join(TMP, f"p_{i}_{prop}.xml")
    with open(path, "w") as f:
        f.write(f'''<?xml version="1.0"?>
<xml_log_file version="1.0">
    <create_attribute attribute_type="source" id="p{i}"/>
    <modify_attribute new_value="3.0" property_name="{prop}">
        <attribute_name id="p{i}"/>
    </modify_attribute>
</xml_log_file>''')
    driver._play_floscript(path)
    time.sleep(1)
    results.append(prop)

_result = results  # then use the Message Window probe above to see which failed
```

The same `#!python` session can drive play + readback — loop over many
candidates in one run without round-tripping to the CLI.

---

## Ground-truth oracle: `<start_record_script>` + `<stop_record_script>`

When you need the authoritative syntax for something, have Flotherm
log it. FloSCRIPT has built-in commands to control recording:

```xml
<xml_log_file version="1.0">
    <start_record_script filename="C:\tmp\recorded.xml"/>
</xml_log_file>
```

Then perform the action of interest (via UIA, or by having a human do it
in RDP), then:

```xml
<xml_log_file version="1.0">
    <stop_record_script/>
</xml_log_file>
```

Read back `recorded.xml` — it contains the exact FloSCRIPT Flotherm would
have emitted for the GUI action. This is the definitive way to learn
syntax for attribute creation, material assignment, power values, BCs, etc.

Related commands:
- `<pause_record_script/>` — pause without stopping
- `<resume_record_script/>` — resume a paused recording

**Prefer this over guessing.** If a property name doesn't work from the
doc, record the equivalent GUI action and compare.
