// starccm_gui_cfd.java — Internal flow using Parts-Based Meshing pipeline
// Uses 3D-CAD Sketch + Extrude to create box with 6 separate faces
import star.common.*;
import star.base.neo.*;
import star.base.report.*;
import star.meshing.*;
import star.flow.*;
import star.material.*;
import star.metrics.*;
import star.segregatedflow.*;
import star.vis.*;
import star.cadmodeler.*;

public class starccm_gui_cfd extends StarMacro {
    public void execute() {
        Simulation sim = getActiveSimulation();
        sim.println("CFD=start");

        try {
            // === Create 3D-CAD with sketch + extrude ===
            sim.println("STEP=cad");
            CadModel cad = sim.get(SolidModelManager.class).createSolidModel(3);
            cad.setPresentationName("Duct");

            // Create sketch on XY plane
            Sketch sketch = cad.createSketch3D(
                sim.getCoordinateSystemManager().getLabCoordinateSystem(),
                true);

            // Draw rectangle: (0,0) to (1, 0.1) on XY plane
            Units m = ((Units) sim.getUnitsManager().getObject("m"));
            sketch.createRectangle(
                sketch.createPoint(new DoubleVector(new double[]{0.0, 0.0}), m),
                sketch.createPoint(new DoubleVector(new double[]{1.0, 0.1}), m));

            // Extrude 0.1m in Z
            Body body = cad.createExtrusionMerge(
                sketch, 0.1, m,
                true, false, false, false);

            cad.update();

            // Create parts from CAD
            cad.createParts();

            // Get the CadPart
            CadPart cadPart = null;
            for (GeometryPart gp : sim.get(SimulationPartManager.class).getParts()) {
                if (gp instanceof CadPart) {
                    cadPart = (CadPart) gp;
                    break;
                }
            }

            sim.println("FACES=" + cadPart.getPartSurfaces().size());
            for (PartSurface ps : cadPart.getPartSurfaces()) {
                sim.println("  FACE: " + ps.getPresentationName());
            }

            // === Create region ===
            sim.println("STEP=region");
            sim.getRegionManager().newRegionsFromParts(
                new NeoObjectVector(new Object[]{cadPart}),
                "OneRegionPerPart",
                null, "OneBoundaryPerPartSurface",
                null, "OneFeatureCurve",
                null, RegionManager.CreateInterfaceMode.BOUNDARY);

            Region region = sim.getRegionManager().getRegions().iterator().next();
            sim.println("BOUNDARIES=" + region.getBoundaryManager().getBoundaries().size());

            Boundary[] bdyArr = region.getBoundaryManager().getBoundaries()
                .toArray(new Boundary[0]);
            for (Boundary b : bdyArr) {
                sim.println("  BDY: " + b.getPresentationName());
            }

            // We expect 6 faces from extruded rectangle
            if (bdyArr.length < 2) {
                sim.println("{\"ok\": false, \"error\": \"need >= 2 boundaries, got " + bdyArr.length + "\"}");
                return;
            }

            // Assign first as inlet, second as outlet
            Boundary inlet = bdyArr[0];
            Boundary outlet = bdyArr[1];
            inlet.setPresentationName("Inlet");
            outlet.setPresentationName("Outlet");
            for (int i = 2; i < bdyArr.length; i++) {
                bdyArr[i].setPresentationName("Wall-" + (i-1));
            }

            // === Mesh ===
            sim.println("STEP=mesh");
            AutoMeshOperation meshOp = sim.get(MeshOperationManager.class)
                .createAutoMeshOperation(
                    new StringVector(new String[]{
                        "star.resurfacer.ResurfacerAutoMesher",
                        "star.trimmer.TrimmerAutoMesher"
                    }),
                    new NeoObjectVector(new Object[]{cadPart}));
            meshOp.getDefaultValues().get(BaseSize.class).setValue(0.01);
            meshOp.execute();

            // === Physics ===
            sim.println("STEP=physics");
            PhysicsContinuum physics = sim.getContinuumManager()
                .createContinuum(PhysicsContinuum.class);
            physics.enable(SteadyModel.class);
            physics.enable(SingleComponentGasModel.class);
            physics.enable(SegregatedFlowModel.class);
            physics.enable(ConstantDensityModel.class);
            physics.enable(LaminarModel.class);
            region.setPhysicsContinuum(physics);

            // === BCs ===
            sim.println("STEP=bcs");
            inlet.setBoundaryType(InletBoundary.class);
            inlet.getValues().get(VelocityMagnitudeProfile.class)
                .getMethod(ConstantScalarProfileMethod.class)
                .getQuantity().setValue(1.0);
            outlet.setBoundaryType(PressureBoundary.class);

            // === Solve ===
            sim.println("STEP=solve");
            ((StepStoppingCriterion) sim.getSolverStoppingCriterionManager()
                .getSolverStoppingCriterion("Maximum Steps"))
                .setMaximumNumberSteps(200);
            sim.getSimulationIterator().run();
            sim.println("SOLVE=done");

            // === Results ===
            sim.println("STEP=results");
            MaxReport maxP = sim.getReportManager().createReport(MaxReport.class);
            maxP.setFieldFunction(sim.getFieldFunctionManager().getFunction("Pressure"));
            maxP.getParts().setObjects(region);
            double pMax = maxP.getValue();

            MinReport minP = sim.getReportManager().createReport(MinReport.class);
            minP.setFieldFunction(sim.getFieldFunctionManager().getFunction("Pressure"));
            minP.getParts().setObjects(region);
            double pMin = minP.getValue();

            MaxReport maxV = sim.getReportManager().createReport(MaxReport.class);
            maxV.setFieldFunction(sim.getFieldFunctionManager().getFunction("Velocity"));
            maxV.getParts().setObjects(region);
            double vMax = maxV.getValue();

            sim.println("PRESSURE_DROP=" + (pMax-pMin) + " Pa, V_MAX=" + vMax + " m/s");

            // === Velocity scene ===
            sim.println("STEP=scene");
            PlaneSection plane = (PlaneSection) sim.getPartManager()
                .createImplicitPart(
                    new NeoObjectVector(new Object[]{region}),
                    new DoubleVector(new double[]{0.0, 0.0, 1.0}),
                    new DoubleVector(new double[]{0.0, 0.0, 0.05}),
                    0, 1, new DoubleVector(new double[]{0.0}));

            Scene scene = sim.getSceneManager().createScene("Velocity");
            ScalarDisplayer sd = scene.getDisplayerManager()
                .createScalarDisplayer("V");
            sd.getScalarDisplayQuantity().setFieldFunction(
                sim.getFieldFunctionManager().getFunction("Velocity"));
            sd.setRepresentation(
                sim.getRepresentationManager().getObject("Volume Mesh"));
            sd.addParts(new NeoObjectVector(new Object[]{plane}));
            scene.setViewOrientation(
                new DoubleVector(new double[]{0.0, 0.0, 1.0}),
                new DoubleVector(new double[]{0.0, 1.0, 0.0}));
            scene.resetCamera();

            String imgPath = sim.getSessionDir() + "/pipe_cfd_velocity.png";
            scene.printAndWait(imgPath, 2, 1920, 1080);

            sim.saveState(sim.getSessionDir() + "/pipe_cfd.sim");

            sim.println("{\"ok\": true, \"pressure_drop_Pa\": " + (pMax-pMin)
                + ", \"max_velocity_ms\": " + vMax + "}");

        } catch (Exception e) {
            String msg = e.getMessage();
            if (msg == null) msg = e.getClass().getName();
            sim.println("{\"ok\": false, \"error\": \"" + msg.replace("\"","'").replace("\\","/") + "\"}");
            e.printStackTrace(new java.io.PrintWriter(System.out));
        }
        sim.println("CFD=done");
    }
}
