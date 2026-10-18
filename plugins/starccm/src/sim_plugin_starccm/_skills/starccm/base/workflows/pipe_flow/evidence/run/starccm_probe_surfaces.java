// Probe what surfaces a SimpleBlockPart has
import star.common.*;
import star.base.neo.*;
import star.meshing.*;

public class starccm_probe_surfaces extends StarMacro {
    public void execute() {
        Simulation sim = getActiveSimulation();

        MeshPartFactory mpf = sim.get(MeshPartFactory.class);
        SimpleBlockPart block = mpf.createNewBlockPart(
            sim.get(SimulationPartManager.class));
        block.setPresentationName("Channel");
        Units m = ((Units) sim.getUnitsManager().getObject("m"));
        block.getCorner1().setCoordinate(m, m, m,
            new DoubleVector(new double[]{0.0, 0.0, 0.0}));
        block.getCorner2().setCoordinate(m, m, m,
            new DoubleVector(new double[]{1.0, 0.1, 0.1}));

        sim.println("=== PartSurfaces ===");
        for (PartSurface ps : block.getPartSurfaces()) {
            sim.println("  PS: " + ps.getPresentationName());
        }

        // Try creating region
        sim.getRegionManager().newRegionsFromParts(
            new NeoObjectVector(new Object[]{block}),
            "OneRegionPerPart",
            null, "OneBoundaryPerPartSurface",
            null, "OneFeatureCurve",
            null, RegionManager.CreateInterfaceMode.BOUNDARY);

        Region region = sim.getRegionManager().getRegion("Channel");
        sim.println("=== Boundaries ===");
        for (Boundary b : region.getBoundaryManager().getBoundaries()) {
            sim.println("  BDY: " + b.getPresentationName());
        }

        // Try listing methods on BoundaryManager for splitting
        sim.println("=== BoundaryManager methods ===");
        for (java.lang.reflect.Method method : region.getBoundaryManager().getClass().getMethods()) {
            if (method.getName().toLowerCase().contains("split")) {
                sim.println("  METHOD: " + method.getName() + " params=" + method.getParameterCount());
            }
        }
    }
}
