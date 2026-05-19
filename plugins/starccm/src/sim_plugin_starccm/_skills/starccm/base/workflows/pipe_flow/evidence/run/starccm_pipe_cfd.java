// starccm_pipe_cfd.java — Complete laminar channel flow CFD
// Uses 3D-CAD model to get proper separate boundaries
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

public class starccm_pipe_cfd extends StarMacro {
    public void execute() {
        Simulation sim = getActiveSimulation();
        sim.println("CFD_PIPE=start");

        try {
            // === Step 1: 3D-CAD box with named faces ===
            sim.println("STEP=geometry");
            CadModel cadModel = sim.get(SolidModelManager.class)
                .createSolidModel(sim.get(SimulationPartManager.class));
            cadModel.setPresentationName("Channel CAD");

            // Create a sketch on XY plane, extrude in Z
            LabCoordinateSystem labCS = sim.getCoordinateSystemManager()
                .getLabCoordinateSystem();

            CadModelCoordinate c1 = cadModel.getCadModelCoordinate(
                labCS, new DoubleVector(new double[]{0.0, 0.0, 0.0}));
            CadModelCoordinate c2 = cadModel.getCadModelCoordinate(
                labCS, new DoubleVector(new double[]{1.0, 0.1, 0.1}));

            Body box = cadModel.createBox(c1, c2);
            cadModel.update();

            // Get the CadPart
            CadPart cadPart = ((CadPart) sim.get(SimulationPartManager.class)
                .getPart("Channel CAD"));

            sim.println("FACES=" + cadPart.getPartSurfaces().size());
            for (PartSurface ps : cadPart.getPartSurfaces()) {
                sim.println("  FACE: " + ps.getPresentationName());
            }

            // === Step 2: Region with OneBoundaryPerPartSurface ===
            sim.println("STEP=region");
            sim.getRegionManager().newRegionsFromParts(
                new NeoObjectVector(new Object[]{cadPart}),
                "OneRegionPerPart",
                null, "OneBoundaryPerPartSurface",
                null, "OneFeatureCurve",
                null, RegionManager.CreateInterfaceMode.BOUNDARY);

            Region region = null;
            for (Region r : sim.getRegionManager().getRegions()) {
                region = r;
                break;
            }
            sim.println("REGION=" + region.getPresentationName());
            sim.println("BOUNDARIES=" + region.getBoundaryManager().getBoundaries().size());

            for (Boundary b : region.getBoundaryManager().getBoundaries()) {
                sim.println("  BDY: " + b.getPresentationName());
            }

            // Identify inlet (x=0 face) and outlet (x=1 face)
            Boundary inlet = null, outlet = null;
            Boundary[] bdyArr = region.getBoundaryManager().getBoundaries()
                .toArray(new Boundary[0]);

            if (bdyArr.length >= 6) {
                // 3D-CAD box: 6 faces. Pick two opposite X faces
                inlet = bdyArr[0];
                outlet = bdyArr[1];
            } else if (bdyArr.length >= 2) {
                inlet = bdyArr[0];
                outlet = bdyArr[1];
            } else {
                // Fallback: single boundary — set as wall, no real CFD possible
                sim.println("{\"ok\": false, \"error\": \"only 1 boundary, cannot set inlet/outlet\"}");
                return;
            }

            inlet.setPresentationName("Inlet");
            outlet.setPresentationName("Outlet");
            for (int i = 2; i < bdyArr.length; i++) {
                bdyArr[i].setPresentationName("Wall-" + (i-1));
            }

            // === Step 3: Mesh ===
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
            sim.println("MESH=done");

            // === Step 4: Physics ===
            sim.println("STEP=physics");
            PhysicsContinuum physics = sim.getContinuumManager()
                .createContinuum(PhysicsContinuum.class);
            physics.setPresentationName("Physics");
            physics.enable(SteadyModel.class);
            physics.enable(SingleComponentGasModel.class);
            physics.enable(SegregatedFlowModel.class);
            physics.enable(ConstantDensityModel.class);
            physics.enable(LaminarModel.class);
            region.setPhysicsContinuum(physics);

            // === Step 5: BCs ===
            sim.println("STEP=bcs");
            inlet.setBoundaryType(InletBoundary.class);
            VelocityMagnitudeProfile vmp = inlet.getValues()
                .get(VelocityMagnitudeProfile.class);
            vmp.getMethod(ConstantScalarProfileMethod.class)
                .getQuantity().setValue(1.0);
            outlet.setBoundaryType(PressureBoundary.class);
            sim.println("BCS=inlet 1m/s, outlet 0Pa");

            // === Step 6: Solve ===
            sim.println("STEP=solve");
            StepStoppingCriterion maxSteps = ((StepStoppingCriterion)
                sim.getSolverStoppingCriterionManager()
                    .getSolverStoppingCriterion("Maximum Steps"));
            maxSteps.setMaximumNumberSteps(200);
            sim.getSimulationIterator().run();
            sim.println("SOLVE=done");

            // === Step 7: Results ===
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

            sim.println("PRESSURE_DROP=" + (pMax - pMin) + " Pa");
            sim.println("V_MAX=" + vMax + " m/s");

            // === Step 8: Velocity scene ===
            sim.println("STEP=scene");
            PlaneSection plane = (PlaneSection) sim.getPartManager()
                .createImplicitPart(
                    new NeoObjectVector(new Object[]{region}),
                    new DoubleVector(new double[]{0.0, 0.0, 1.0}),
                    new DoubleVector(new double[]{0.0, 0.0, 0.05}),
                    0, 1, new DoubleVector(new double[]{0.0}));
            plane.setPresentationName("Mid Plane Z");

            Scene scene = sim.getSceneManager().createScene("Velocity");
            ScalarDisplayer sd = scene.getDisplayerManager()
                .createScalarDisplayer("Velocity Mag");
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
            sim.println("IMAGE=" + imgPath);

            sim.saveState(sim.getSessionDir() + "/pipe_cfd.sim");

            sim.println("{\"ok\": true"
                + ", \"pressure_drop_Pa\": " + (pMax - pMin)
                + ", \"max_velocity_ms\": " + vMax
                + ", \"p_max_Pa\": " + pMax
                + ", \"p_min_Pa\": " + pMin + "}");

        } catch (Exception e) {
            String msg = e.getMessage();
            if (msg == null) msg = e.getClass().getName();
            msg = msg.replace("\"", "'").replace("\\", "/").replace("\n", " ");
            sim.println("{\"ok\": false, \"error\": \"" + msg + "\"}");
            e.printStackTrace(new java.io.PrintWriter(System.out));
        }

        sim.println("CFD_PIPE=done");
    }
}
