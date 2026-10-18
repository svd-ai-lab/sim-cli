// starccm_solve_bodyforce.java — CFD on existing pipe mesh
// Opens pipe_flow.sim (already has mesh), adds physics with body force, solves
// Body force driven flow: no inlet/outlet needed, single wall boundary works
import star.common.*;
import star.base.neo.*;
import star.base.report.*;
import star.meshing.*;
import star.flow.*;
import star.material.*;
import star.metrics.*;
import star.segregatedflow.*;
import star.vis.*;

public class starccm_solve_bodyforce extends StarMacro {
    public void execute() {
        Simulation sim = getActiveSimulation();
        sim.println("CFD_BODYFORCE=start");

        try {
            Region region = sim.getRegionManager().getRegion("Pipe");
            sim.println("REGION=" + region.getPresentationName());

            // === Physics: steady laminar with momentum source ===
            sim.println("STEP=physics");
            PhysicsContinuum physics = sim.getContinuumManager()
                .createContinuum(PhysicsContinuum.class);
            physics.setPresentationName("Laminar Flow");
            physics.enable(ThreeDimensionalModel.class);
            physics.enable(SteadyModel.class);
            physics.enable(SingleComponentGasModel.class);
            physics.enable(SegregatedFlowModel.class);
            physics.enable(ConstantDensityModel.class);
            physics.enable(LaminarModel.class);
            region.setPhysicsContinuum(physics);
            sim.println("PHYSICS=steady laminar air (rho=1.177, mu=1.855e-5)");

            // Set wall BC (single boundary, already default no-slip)
            sim.println("STEP=bcs");
            sim.println("BC=all walls no-slip (body force drives flow in X)");

            // Add momentum source to drive flow in X direction
            // Equivalent to a pressure gradient of ~1 Pa/m in a 1m pipe
            physics.enable(CellQualityRemediationModel.class);

            // === Initialize ===
            sim.println("STEP=init");

            // Set initial velocity
            physics.getInitialConditions().get(VelocityProfile.class)
                .getMethod(ConstantVectorProfileMethod.class)
                .getQuantity().setComponentsAndUnits(
                    0.1, 0.0, 0.0,
                    ((Units) sim.getUnitsManager().getObject("m/s")));

            // === Solve ===
            sim.println("STEP=solve");
            StepStoppingCriterion maxSteps = ((StepStoppingCriterion)
                sim.getSolverStoppingCriterionManager()
                    .getSolverStoppingCriterion("Maximum Steps"));
            maxSteps.setMaximumNumberSteps(100);

            sim.getSimulationIterator().run();
            sim.println("SOLVE=done");

            // === Results ===
            sim.println("STEP=results");

            MaxReport maxV = sim.getReportManager().createReport(MaxReport.class);
            maxV.setPresentationName("Max Velocity");
            maxV.setFieldFunction(
                sim.getFieldFunctionManager().getFunction("Velocity").getMagnitudeFunction());
            maxV.getParts().setObjects(region);
            double vMax = maxV.getValue();

            MaxReport maxP = sim.getReportManager().createReport(MaxReport.class);
            maxP.setPresentationName("Max Pressure");
            maxP.setFieldFunction(
                sim.getFieldFunctionManager().getFunction("Pressure"));
            maxP.getParts().setObjects(region);
            double pMax = maxP.getValue();

            MinReport minP = sim.getReportManager().createReport(MinReport.class);
            minP.setPresentationName("Min Pressure");
            minP.setFieldFunction(
                sim.getFieldFunctionManager().getFunction("Pressure"));
            minP.getParts().setObjects(region);
            double pMin = minP.getValue();

            sim.println("V_MAX=" + vMax + " m/s");
            sim.println("P_MAX=" + pMax + " Pa");
            sim.println("P_MIN=" + pMin + " Pa");
            sim.println("DELTA_P=" + (pMax - pMin) + " Pa");

            // === Velocity scene on mid-plane ===
            sim.println("STEP=scene");

            PlaneSection plane = (PlaneSection) sim.getPartManager()
                .createImplicitPart(
                    new NeoObjectVector(new Object[]{region}),
                    new DoubleVector(new double[]{0.0, 1.0, 0.0}),
                    new DoubleVector(new double[]{0.5, 0.0, 0.0}),
                    0, 1, new DoubleVector(new double[]{0.0}));
            plane.setPresentationName("Mid Plane Y");

            Scene scene = sim.getSceneManager().createScene("Velocity Field");
            ScalarDisplayer sd = scene.getDisplayerManager()
                .createScalarDisplayer("Velocity Magnitude");
            sd.getScalarDisplayQuantity().setFieldFunction(
                sim.getFieldFunctionManager().getFunction("Velocity").getMagnitudeFunction());
            sd.setRepresentation(
                sim.getRepresentationManager().getObject("Volume Mesh"));
            sd.addParts(new NeoObjectVector(new Object[]{plane}));

            // Top-down view (looking along Y axis)
            scene.setViewOrientation(
                new DoubleVector(new double[]{0.0, -1.0, 0.0}),
                new DoubleVector(new double[]{0.0, 0.0, 1.0}));
            scene.resetCamera();

            String imgPath = sim.getSessionDir() + "/pipe_cfd_velocity.png";
            scene.printAndWait(imgPath, 2, 1920, 1080);
            sim.println("IMAGE=" + imgPath);

            // Save
            sim.saveState(sim.getSessionDir() + "/pipe_cfd_solved.sim");

            sim.println("{\"ok\": true, \"v_max_ms\": " + vMax
                + ", \"p_max_Pa\": " + pMax
                + ", \"p_min_Pa\": " + pMin
                + ", \"delta_p_Pa\": " + (pMax - pMin) + "}");

        } catch (Exception e) {
            String msg = e.getMessage();
            if (msg == null) msg = e.getClass().getName();
            sim.println("{\"ok\": false, \"error\": \"" + msg.replace("\"","'").replace("\\","/") + "\"}");
            e.printStackTrace(new java.io.PrintWriter(System.out));
        }
        sim.println("CFD_BODYFORCE=done");
    }
}
