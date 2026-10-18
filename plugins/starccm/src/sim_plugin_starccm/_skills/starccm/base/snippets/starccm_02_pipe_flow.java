// starccm_02_pipe_flow.java — Create geometry + mesh workflow
// Acceptance: exit_code == 0, JSON contains ok=true with boundary and region info
//
// Self-contained: does NOT require a pre-existing .sim file.
import star.common.*;
import star.base.neo.*;
import star.meshing.*;

public class starccm_02_pipe_flow extends StarMacro {
    public void execute() {
        Simulation sim = getActiveSimulation();
        sim.println("PIPE_FLOW=start");

        try {
            // --- Step 1: Create geometry (simple cylinder) ---
            sim.println("STEP=create_geometry");
            MeshPartFactory partFactory = sim.get(MeshPartFactory.class);
            SimpleCylinderPart cylinder = partFactory.createNewCylinderPart(
                sim.get(SimulationPartManager.class));
            cylinder.setPresentationName("Pipe");

            // Set dimensions: radius=0.05m, length=1.0m
            Units meters = ((Units) sim.getUnitsManager().getObject("m"));
            cylinder.getRadius().setValueAndUnits(0.05, meters);
            cylinder.getStartCoordinate().setCoordinate(meters, meters, meters,
                new DoubleVector(new double[]{0.0, 0.0, 0.0}));
            cylinder.getEndCoordinate().setCoordinate(meters, meters, meters,
                new DoubleVector(new double[]{1.0, 0.0, 0.0}));
            sim.println("GEOMETRY=pipe created (R=0.05m, L=1.0m)");

            // --- Step 2: Create region from part ---
            sim.println("STEP=create_region");
            sim.getRegionManager().newRegionsFromParts(
                new java.util.ArrayList<GeometryPart>(
                    java.util.Arrays.asList(new GeometryPart[]{cylinder})),
                "OneRegionPerPart",
                null, "OneBoundaryPerPartSurface",
                null, "OneFeatureCurve",
                null, RegionManager.CreateInterfaceMode.BOUNDARY);

            Region region = sim.getRegionManager().getRegion("Pipe");
            int boundaryCount = region.getBoundaryManager().getBoundaries().size();
            sim.println("BOUNDARY_COUNT=" + boundaryCount);

            // List boundaries
            StringBuilder bnames = new StringBuilder();
            for (Boundary b : region.getBoundaryManager().getBoundaries()) {
                if (bnames.length() > 0) bnames.append(", ");
                bnames.append(b.getPresentationName());
            }
            sim.println("BOUNDARIES=" + bnames.toString());

            // --- Step 3: Generate mesh ---
            sim.println("STEP=mesh");
            AutoMeshOperation meshOp = sim.get(MeshOperationManager.class)
                .createAutoMeshOperation(
                    new StringVector(new String[]{
                        "star.resurfacer.ResurfacerAutoMesher",
                        "star.trimmer.TrimmerAutoMesher"
                    }),
                    new NeoObjectVector(new Object[]{cylinder}));
            meshOp.getDefaultValues().get(BaseSize.class).setValue(0.01);
            meshOp.execute();
            sim.println("MESH=generated");

            // Get region cell count
            int regionCount = sim.getRegionManager().getRegions().size();

            // --- Build result JSON ---
            sim.println("{\"ok\": true, \"regions\": " + regionCount
                + ", \"boundaries\": " + boundaryCount
                + ", \"mesh_generated\": true"
                + ", \"step\": \"mesh_complete\"}");

        } catch (Exception e) {
            String msg = e.getMessage();
            if (msg == null) msg = e.getClass().getName();
            sim.println("{\"ok\": false, \"error\": \"" + msg.replace("\"", "'").replace("\\", "/") + "\"}");
        }

        sim.println("PIPE_FLOW=done");
    }
}
