// starccm_pipe_flow_visual.java
// Creates cylinder geometry + trimmer mesh + mesh scene + exports image
import star.common.*;
import star.base.neo.*;
import star.meshing.*;
import star.vis.*;

public class starccm_pipe_flow_visual extends StarMacro {
    public void execute() {
        Simulation sim = getActiveSimulation();
        sim.println("PIPE_FLOW_VISUAL=start");

        try {
            // --- Step 1: Create cylinder geometry ---
            sim.println("STEP=geometry");
            MeshPartFactory partFactory = sim.get(MeshPartFactory.class);
            SimpleCylinderPart cylinder = partFactory.createNewCylinderPart(
                sim.get(SimulationPartManager.class));
            cylinder.setPresentationName("Pipe");

            Units meters = ((Units) sim.getUnitsManager().getObject("m"));
            cylinder.getRadius().setValueAndUnits(0.05, meters);
            cylinder.getStartCoordinate().setCoordinate(meters, meters, meters,
                new DoubleVector(new double[]{0.0, 0.0, 0.0}));
            cylinder.getEndCoordinate().setCoordinate(meters, meters, meters,
                new DoubleVector(new double[]{1.0, 0.0, 0.0}));

            // --- Step 2: Create region ---
            sim.println("STEP=region");
            sim.getRegionManager().newRegionsFromParts(
                new java.util.ArrayList<GeometryPart>(
                    java.util.Arrays.asList(new GeometryPart[]{cylinder})),
                "OneRegionPerPart",
                null, "OneBoundaryPerPartSurface",
                null, "OneFeatureCurve",
                null, RegionManager.CreateInterfaceMode.BOUNDARY);

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
            sim.println("MESH=done");

            // --- Step 4: Create mesh scene and export image ---
            sim.println("STEP=scene");
            Scene meshScene = sim.getSceneManager().createScene("Mesh");
            // Add mesh displayer
            PartDisplayer pd = meshScene.getDisplayerManager().createPartDisplayer("Mesh Surface");
            pd.setRepresentation(
                sim.getRepresentationManager().getObject("Volume Mesh"));
            pd.addParts(new NeoObjectVector(
                sim.getRegionManager().getRegions().toArray()));
            pd.setSurface(true);
            pd.setMesh(true);

            // Export image
            String imgPath = sim.getSessionDir() + java.io.File.separator + "pipe_mesh_scene.png";
            meshScene.printAndWait(imgPath, 1, 1280, 720);
            sim.println("IMAGE=" + imgPath);

            // --- Step 5: Save sim file ---
            String simPath = sim.getSessionDir() + java.io.File.separator + "pipe_flow.sim";
            sim.saveState(simPath);
            sim.println("SAVED=" + simPath);

            sim.println("{\"ok\": true, \"mesh_generated\": true, \"image\": \"" + imgPath + "\"}");

        } catch (Exception e) {
            String msg = e.getMessage();
            if (msg == null) msg = e.getClass().getName();
            sim.println("{\"ok\": false, \"error\": \"" + msg.replace("\"", "'").replace("\\", "/") + "\"}");
        }

        sim.println("PIPE_FLOW_VISUAL=done");
    }
}
