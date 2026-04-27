# Static Structural Workflow

The Workbench **Static Structural** system has 6 standard cells:

```
Engineering Data → Geometry → Model → Setup → Solution → Results
        ↓             ↓         ↓       ↓        ↓         ↓
     materials    CAD file   mesh    BCs/loads  solve   post-process
```

**Workbench skill responsibility**: Cells 1-3 (Engineering Data, Geometry, Model).
**PyMechanical skill responsibility**: Cells 4-6 (Setup, Solution, Results).

See [`evidence/`](evidence/) for visual proof (screenshots) of Workbench
successfully taking cells 1-3 from `?` to green checkmark on real Ansys 24.1.

> **First principles**: PyWorkbench orchestrates projects. PyMechanical
> drives Mechanical. Keep them distinct — don't use Workbench scripting
> to do what belongs in Mechanical.

---

## Step 1: Engineering Data

Materials library for the analysis. Managed through the Engineering Data container.

### What works

```python
s = GetAllSystems()[0]
eng = s.GetContainer(ComponentName="Engineering Data")

# List all materials
mats = eng.GetMaterials()
# Default: [Structural Steel] — every new Static Structural system has this

# Get a specific material by name
steel = eng.GetMaterial(Name="Structural Steel")

# Create a new material
new_mat = eng.CreateMaterial(Name="Test_Aluminum")

# Import materials from a library
# eng.Import(FilePath="my_materials.xml")
```

### Key APIs

| Method | Purpose |
|--------|---------|
| `GetMaterials()` | List all materials in the project |
| `GetMaterial(Name=...)` | Fetch one material by name |
| `CreateMaterial(Name=...)` | Add a new (empty) material |
| `Import(FilePath=...)` | Import material library file |
| `ImportMaterial(...)` | Import a single material |

### Gotchas

- The newly created material is **empty** — you must set properties via
  the Engineering Data GUI or via PyMechanical later.
- Material names are case-sensitive.

---

## Step 2: Geometry

Attach a CAD file to feed the analysis.

### What works

```python
s = GetAllSystems()[0]
geo = s.GetContainer(ComponentName="Geometry")

# Get current properties
props = geo.GetGeometryProperties()
# Returns a property object even when no file is attached

# Attach a file — MUST use absolute path
import os
geo_path = os.path.join(os.environ["TEMP"], "my_part.agdb")
geo.SetFile(FilePath=geo_path)

# Other ops
geo.Edit()        # Opens SpaceClaim/DesignModeler
geo.Refresh()     # Re-read the file
geo.UpdateCAD()   # Pull updates from CAD
```

### Key APIs

| Method | Purpose |
|--------|---------|
| `SetFile(FilePath=...)` | Attach a .agdb/.scdoc/.stp file (**absolute path**) |
| `GetGeometryProperties()` | Get the geometry properties object |
| `Edit()` | Open the geometry editor (SpaceClaim/DM) |
| `Refresh()` | Re-read the attached file |
| `UpdateCAD()` | Pull fresh data from CAD |
| `GetFiles()` | List files attached to this cell |
| `Export(FilePath=...)` | Export to another format |

### Gotchas

- **`SetFile` requires absolute path**: Workbench's server CWD is
  `c:\windows\system32\spool\drivers\x64\3\`, NOT the upload directory.
  Relative paths silently fail with "geometry file does not exist".
  Always use `os.path.join(os.environ["TEMP"], "file.agdb")`.
- **`upload_file_from_example_repo` may return HTML** (SDK 0.4 bug):
  verify the downloaded file is not HTML before upload.
- Actual parsing of the `.agdb` happens during `system.Update()` via
  SpaceClaim/DesignModeler — this is heavy and may block for minutes.

---

## Step 3: Model

Mesh management and physics-class identification.

### What works

```python
s = GetAllSystems()[0]
model = s.GetContainer(ComponentName="Model")

# CANONICAL way to identify system physics type
phys = model.GetMechanicalSystemType()
# Returns: "SystemClass for Structural|Static|ANSYS"

# Mesh export
model.ExportMesh(FilePath="mesh.msh")
model.GetMechanicalMeshFile()  # Get the mesh file path on server

# Properties
props = model.GetMeshProperties()
```

### Key APIs

| Method | Purpose |
|--------|---------|
| `GetMechanicalSystemType()` | **Canonical physics query** (works anytime) |
| `GetMechanicalMesh()` | Access the mesh object |
| `GetMechanicalMeshFile()` | Path to the mesh file |
| `ExportMesh(FilePath=...)` | Export mesh to file |
| `ExportGeometry(FilePath=...)` | Export geometry (post-mesh) |
| `Edit()` | Open Mechanical |

### Gotchas

- **Use `Model.GetMechanicalSystemType()` for physics queries**, NOT
  `Setup.GetPhysicsType()` — see next step.
- `ExportMesh` requires the mesh to already be generated (via Mechanical
  or by updating the Model cell).

---

## Step 4: Setup ⚠️

Boundary conditions, loads, contacts. **This is where Mechanical takes over**.

### What works

```python
s = GetAllSystems()[0]
setup = s.GetContainer(ComponentName="Setup")

# Open Mechanical for interactive setup
setup.Edit()

# Get the server-side setup file path (for post-mortem inspection)
file_path = setup.GetMechanicalSetupFile()

# Send command to Mechanical (low-level)
# setup.SendCommand(Command="...")
```

### Key APIs

| Method | Purpose |
|--------|---------|
| `Edit()` | Open Mechanical for interactive BC/load setup |
| `Exit()` | Close Mechanical |
| `GetMechanicalSetupFile()` | Path to the setup database |
| `GetMechanicalSystemType()` | Physics class (same as Model) |
| `SendCommand(Command=...)` | Send raw command to Mechanical |

### ⚠️ GOTCHA: Don't use `GetPhysicsType()` on Setup

```python
# ❌ FAILS before solve has run
setup.GetPhysicsType()
# Error: "Setup不包含所需的实体类型PhysicsType"

# ✅ WORKS anytime
model.GetMechanicalSystemType()
```

**Why**: `PhysicsType` is a result-data property that only exists after
solve. `MechanicalSystemType` is metadata available immediately.

### Actual BC/load definition

Must happen in Mechanical via:

1. **Interactive**: `setup.Edit()` → user places BCs in GUI → save
2. **Programmatic**: Use **PyMechanical skill** (separate). From Workbench:
   ```python
   port = wb.start_mechanical_server(system_name=s.Name)
   # Then PyMechanical takes over — NOT Workbench skill's job
   ```

---

## Step 5: Solution ⚠️

Solver settings and execution trigger.

### What works

```python
s = GetAllSystems()[0]
sol = s.GetContainer(ComponentName="Solution")

# Expert properties (works even before solve)
props = sol.GetExpertProperties()

# Solver settings access (for configuration export)
settings = sol.GetSolutionSettings()

# Open solution for inspection
sol.Edit()
```

### Key APIs

| Method | Purpose |
|--------|---------|
| `GetExpertProperties()` | Advanced solver settings (works anytime) |
| `GetSolutionSettings()` | Core solution settings object |
| `Edit()` | Open Mechanical at solution level |
| `GetComponentSettingsForRsmDpUpdate()` | For RSM/design points |
| `SendCommand(Command=...)` | Raw command to solution |

### ⚠️ GOTCHA: Same `GetPhysicsType()` trap

```python
# ❌ FAILS before solve
sol.GetPhysicsType()
# Error: "Solution不包含所需的实体类型PhysicsType"

# ✅ Use Model instead
model.GetMechanicalSystemType()
```

### Triggering the actual solve

**Not Workbench's job**. Two options:

1. **Via Workbench update cascade**: `system1.Update()` will drive Mechanical
   to solve if BCs are valid. This is a blocking call.
2. **Via PyMechanical**: Connect to Mechanical server and call
   `Model.Analyses[0].Solve(True)`. This is the PyMechanical skill's role.

---

## Step 6: Results

Post-processing result file access.

### What works

```python
s = GetAllSystems()[0]
res = s.GetContainer(ComponentName="Results")

# Path to the .rst (ANSYS result file)
rst_path = res.GetSimulationResultFile()

# Open post-processor
res.EditPost()
```

### Key APIs

| Method | Purpose |
|--------|---------|
| `GetSimulationResultFile()` | Path to .rst result file |
| `GetSimulationImportOptionsForResult()` | Import options for external post |
| `Edit()` | Open Mechanical Results |
| `EditPost()` | Open standalone post-processor |

### ⚠️ GOTCHA: Same `GetPhysicsType()` trap (last time!)

All post-solve query methods (`GetPhysicsType`, etc.) on Setup/Solution/Results
fail before the solve completes. **Always query physics from
`Model.GetMechanicalSystemType()`**.

### Extracting results

Like solve, this is PyMechanical's job. From Workbench you can:

1. **Download the .rst** after solve completes:
   ```python
   rst_server = res.GetSimulationResultFile()
   wb.download_file(os.path.basename(rst_server), target_dir=".")
   ```

2. **Hand off to PyMechanical**: Start Mechanical server, let PyMechanical
   traverse the results tree, extract deformation/stress/etc.

---

## Full workflow walk (Workbench-side only)

```python
import os
import ansys.workbench.core as pywb

wb = pywb.launch_workbench(release="241")

# 1. Create system
wb.run_script_string('''
SetScriptVersion(Version="24.1")
t = GetTemplate(TemplateName="Static Structural", Solver="ANSYS")
s = t.CreateSystem()
''')

# 2. Upload geometry
wb.upload_file("my_part.agdb")

# 3. Walk all 6 cells
wb.run_script_string('''
import os, json, codecs
s = GetAllSystems()[0]

# Engineering Data: verify default material
eng = s.GetContainer(ComponentName="Engineering Data")
mats = eng.GetMaterials()
assert len(mats) >= 1  # Structural Steel

# Geometry: attach file (absolute path!)
geo = s.GetContainer(ComponentName="Geometry")
geo_path = os.path.join(os.environ["TEMP"], "my_part.agdb")
geo.SetFile(FilePath=geo_path)

# Model: query physics class
model = s.GetContainer(ComponentName="Model")
phys = str(model.GetMechanicalSystemType())  # "SystemClass for Structural|Static|ANSYS"

# Setup/Solution/Results: check API availability (do NOT call GetPhysicsType)
setup = s.GetContainer(ComponentName="Setup")
sol = s.GetContainer(ComponentName="Solution")
res = s.GetContainer(ComponentName="Results")

# Save the project
Save(FilePath=os.path.join(os.environ["TEMP"], "workflow.wbpj"), Overwrite=True)
''')

# 4. Hand off to Mechanical for actual solve
port = wb.start_mechanical_server(system_name="SYS")
# >>> Switch to PyMechanical skill from here <<<

# 5. After Mechanical finishes, orchestrate results
wb.run_script_string('''
import os
s = GetAllSystems()[0]

# Archive the project
Save(Overwrite=True)
Archive(FilePath=os.path.join(os.environ["TEMP"], "workflow.wbpz"))
''')

# 6. Download the archive
wb.download_file("workflow.wbpz", target_dir="./output")
```

---

## Summary of APIs per cell

| Cell | Key method | Purpose |
|------|-----------|---------|
| Engineering Data | `GetMaterials()`, `CreateMaterial()` | Material CRUD |
| Geometry | `SetFile(absolute_path)`, `Refresh()` | File attachment |
| Model | `GetMechanicalSystemType()`, `ExportMesh()` | **Physics query** |
| Setup | `Edit()`, `GetMechanicalSetupFile()` | Open Mechanical |
| Solution | `GetExpertProperties()`, `GetSolutionSettings()` | Solver config |
| Results | `GetSimulationResultFile()`, `EditPost()` | Result file access |

## Summary of gotchas

1. **`SetFile` needs absolute path** — CWD ≠ TEMP
2. **`Setup/Solution/Results.GetPhysicsType()` fails before solve** — use `Model.GetMechanicalSystemType()` instead
3. **`Archive()` requires prior `Save()`** — archive-before-save fails
4. **Actual mesh/BC/solve/post is Mechanical's job** — don't try to do it through Workbench scripting
5. **`upload_file_from_example_repo` may download HTML** on SDK 0.4 — verify bytes before use
