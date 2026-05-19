// export_mesh_scene.java
// Opens saved pipe_flow.sim, creates a proper mesh scene, exports image
import star.common.*;
import star.base.neo.*;
import star.vis.*;

public class export_mesh_scene extends StarMacro {
    public void execute() {
        Simulation sim = getActiveSimulation();

        // Get the region
        Region region = sim.getRegionManager().getRegion("Pipe");
        sim.println("Region: " + region.getPresentationName());

        // Create a geometry scene (shows the part surfaces with mesh overlay)
        sim.getSceneManager().deleteScenes(
            new NeoObjectVector(sim.getSceneManager().getScenes().toArray()));

        Scene scene = sim.getSceneManager().createScene("Mesh Scene");

        // Use a standard mesh displayer approach
        CurrentView cv = scene.getCurrentView();

        // Add part displayer showing the region
        PartDisplayer pd = scene.getDisplayerManager().createPartDisplayer("Mesh");
        pd.setOutline(false);
        pd.setSurface(true);
        pd.setMesh(true);
        pd.setColorMode(PartColorMode.CONSTANT);
        pd.setRepresentation(
            sim.getRepresentationManager().getObject("Volume Mesh"));

        // Add the region's boundaries
        java.util.Collection<Boundary> boundaries = region.getBoundaryManager().getBoundaries();
        pd.addParts(new NeoObjectVector(boundaries.toArray()));

        // Fit the view
        scene.setViewOrientation(new DoubleVector(new double[]{-1.0, -1.0, 1.0}),
            new DoubleVector(new double[]{0.0, 0.0, 1.0}));
        scene.resetCamera();

        // Export
        String imgPath = sim.getSessionDir() + java.io.File.separator + "pipe_mesh_scene.png";
        scene.printAndWait(imgPath, 2, 1920, 1080);
        sim.println("IMAGE_EXPORTED=" + imgPath);

        // Also save
        sim.saveState(sim.getSessionDir() + java.io.File.separator + "pipe_flow.sim");
    }
}
