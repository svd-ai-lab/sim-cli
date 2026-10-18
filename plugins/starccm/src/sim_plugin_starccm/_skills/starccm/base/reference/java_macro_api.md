# Star-CCM+ Java Macro API Reference

## Macro structure

Every macro follows this skeleton:

```java
import star.common.*;

public class MyMacro extends StarMacro {
    public void execute() {
        Simulation sim = getActiveSimulation();
        // ... macro logic ...
    }
}
```

- `StarMacro` — base class (from `star.common`)
- `execute()` — entry point called by the engine
- `getActiveSimulation()` — returns the `Simulation` object
- `resolvePath(String)` — resolve file path relative to macro location

---

## Key packages

| Package | Contents |
|---------|----------|
| `star.common.*` | Simulation, Region, Boundary, PhysicsContinuum, Units, FieldFunction |
| `star.base.neo.*` | DoubleVector, StringVector, NeoProperty |
| `star.base.report.*` | Report, Monitor, MaxReport |
| `star.flow.*` | VelocityProfile, InletVelocityOption |
| `star.segregatedflow.*` | Segregated flow solver |
| `star.coupledflow.*` | Coupled flow solver |
| `star.energy.*` | Energy/thermal models |
| `star.turbulence.*` | RANS turbulence models |
| `star.kwturb.*` | k-omega turbulence |
| `star.meshing.*` | AutoMeshOperation, MeshOperationManager |
| `star.cadmodeler.*` | Body, CadModel |
| `star.vis.*` | Scene, Displayer, PlaneSection |

---

## Simulation object — key methods

| Method | Purpose |
|--------|---------|
| `getPresentationName()` | Simulation display name |
| `getRegionManager()` | Access regions |
| `getContinuumManager()` | Access physics continua |
| `get(MeshOperationManager.class)` | Get mesh operations manager |
| `getSimulationIterator().run()` | Run the solver |
| `getSolverStoppingCriterionManager()` | Set stopping criteria |
| `getReportManager()` | Create/access reports |
| `getPlotManager()` | XY plots |
| `getSceneManager()` | 3D scenes |
| `getFieldFunctionManager()` | Field functions |
| `getImportManager()` | Import geometry/mesh |
| `saveState(String path)` | Save .sim file |
| `println(String)` | Print to output (use for JSON results) |

---

## Common patterns

### Physics setup

```java
PhysicsContinuum physics = (PhysicsContinuum) sim
    .getContinuumManager().getContinuum("Physics 1");
physics.enable(SteadyModel.class);
physics.enable(SingleComponentGasModel.class);
physics.enable(SegregatedFlowModel.class);
physics.enable(RansTurbulenceModel.class);
physics.enable(KEpsilonTurbulence.class);
```

### Region and boundary access

```java
Region region = sim.getRegionManager().getRegion("Fluid");
Boundary inlet = region.getBoundaryManager().getBoundary("Inlet");
Boundary outlet = region.getBoundaryManager().getBoundary("Outlet");
```

### Set boundary condition

```java
inlet.getConditions().get(InletVelocityOption.class)
    .setSelected(InletVelocityOption.MAGNITUDE_DIRECTION);
VelocityProfile vp = inlet.getValues().get(VelocityProfile.class);
vp.getMethod(ConstantScalarProfileMethod.class)
    .getQuantity().setValue(5.0);
```

### Generate mesh

```java
AutoMeshOperation meshOp = (AutoMeshOperation) sim
    .get(MeshOperationManager.class).getObject("Automated Mesh");
meshOp.execute();
```

### Run solver

```java
StepStoppingCriterion stopCrit = (StepStoppingCriterion) sim
    .getSolverStoppingCriterionManager()
    .getSolverStoppingCriterion("Maximum Steps");
stopCrit.setMaximumNumberSteps(1000);
sim.getSimulationIterator().run();
```

### Extract report value

```java
Report forceReport = sim.getReportManager().getReport("Drag Force");
double value = forceReport.getReportMonitorValue();
sim.println("{\"drag\": " + value + "}");
```

### Export scene image

```java
Scene scene = sim.getSceneManager().getScene("Scalar Scene 1");
scene.printAndWait(resolvePath("output.jpg"), 1, 800, 450);
```

### Import geometry

```java
sim.getImportManager().importMeshFiles(
    new StringVector(new String[] { resolvePath("geometry.ccm") }),
    NeoProperty.fromString("{'FileOptions': [{'Sequence': 42}]}")
);
```

---

## Output convention for sim-cli

End every macro with a JSON output line for `parse_output()`:

```java
sim.println("{\"ok\": true, \"cells\": " + cellCount + ", \"drag\": " + drag + "}");
```

The driver extracts the last JSON line from stdout.

---

## API discovery via macro recorder

The fastest way to find the correct API call:
1. Open Star-CCM+ GUI
2. **Tools > Macro > Start Recording**
3. Perform the operation manually
4. **Tools > Macro > Stop Recording**
5. Read the generated `.java` file
6. Adapt the recorded code into your macro
